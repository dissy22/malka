from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=15, h_spacing=18, v_spacing=18):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.item_list = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self.item_list.append(item)

    def horizontalSpacing(self):
        return self._h_spacing

    def verticalSpacing(self):
        return self._v_spacing

    def count(self):
        return len(self.item_list)

    def itemAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.item_list):
            return self.item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        # QScrollArea + widgetResizable + heightForWidth causes an endless
        # width/height feedback loop on large grids (scrollbar appears ->
        # viewport width changes -> heightForWidth -> minimum height changes).
        # MainWindow computes and sets the container height explicitly, so Qt
        # must not drive it through heightForWidth.
        return False

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.item_list:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def clear(self):
        while self.count():
            item = self.takeAt(0)
            if item:
                wid = item.widget()
                if wid:
                    wid.hide()
                    wid.deleteLater()

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())

        space_x = self.horizontalSpacing()
        space_y = self.verticalSpacing()
        eff_w = max(0, effective_rect.width())

        # QLayout calls heightForWidth()/setGeometry() repeatedly while a grid is
        # being built. Resolve widget pointers and size hints only once per pass
        # instead of several times per item; this is the hottest path when
        # switching between large album/artist libraries.
        visible = []
        for item in self.item_list:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            size = item.sizeHint()
            visible.append((item, widget, size, bool(getattr(widget, "is_section_header", False))))

        if not visible:
            return margins.top() + margins.bottom()

        # Group items into lines (rows)
        lines = []
        current_line = []
        current_line_w = 0

        for entry in visible:
            if entry[3]:
                if current_line:
                    lines.append(current_line)
                    current_line = []
                    current_line_w = 0
                lines.append([entry])
                continue

            iw = entry[2].width()
            needed_w = iw if not current_line else (current_line_w + space_x + iw)
            if current_line and needed_w > eff_w:
                lines.append(current_line)
                current_line = [entry]
                current_line_w = iw
            else:
                current_line.append(entry)
                current_line_w = needed_w

        if current_line:
            lines.append(current_line)

        # Calculate max row width across regular card lines to center the grid.
        max_row_w = 0
        for line in lines:
            if len(line) == 1 and line[0][3]:
                continue
            line_w = sum(entry[2].width() for entry in line) + max(0, len(line) - 1) * space_x
            max_row_w = max(max_row_w, line_w)

        offset_x = max(0, (eff_w - max_row_w) // 2)

        y = effective_rect.y()
        for line in lines:
            if len(line) == 1 and line[0][3]:
                header_item, _widget, header_size, _ = line[0]
                header_h = header_size.height()
                header_w = max_row_w if max_row_w > 0 else eff_w
                if not test_only:
                    header_item.setGeometry(QRect(effective_rect.x() + offset_x, y, header_w, header_h))
                y += header_h + space_y
                continue

            line_h = 0
            x = effective_rect.x() + offset_x
            for item, _widget, size, _ in line:
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), size))
                x += size.width() + space_x
                line_h = max(line_h, size.height())
            y += line_h + space_y

        total_h = y - space_y - rect.y() + margins.bottom() if lines else (margins.top() + margins.bottom())
        # NOTE: minimumHeight is deliberately NOT updated here. Doing it from
        # inside a layout pass caused recursive relayouts; MainWindow updates the
        # container height explicitly after rendering/resizing instead.
        return total_h
