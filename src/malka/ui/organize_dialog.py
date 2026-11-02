from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from malka.config import config
from malka.organizer import build_organization_plan


class OrganizeDialog(QDialog):
    """Preview of every file rename/move before organizing an album.

    The user picks the target library root (defaults to the root that currently
    holds the files) and sees the exact "current path -> new path" list. The
    left and right columns are independent panes, each with its own horizontal
    scrollbar, so long paths can be read to the end without hiding the other
    side. A checkbox toggles between the compact "differences only" view and
    the full paths.
    """

    def __init__(
        self,
        tracks: List[Dict[str, Any]],
        library_roots: List[str],
        default_root: str,
        template: str,
        parent=None,
        theme: Optional[str] = None,
    ):
        super().__init__(parent)
        self.tracks = [dict(t) for t in tracks]
        self.library_roots = [str(p) for p in library_roots]
        self.default_root = default_root or (self.library_roots[0] if self.library_roots else "")
        self.template = template
        self._plan: List[Dict[str, Any]] = []
        self._syncing_scroll = False

        if theme is not None:
            self.theme = theme
        elif hasattr(parent, "theme"):
            self.theme = parent.theme
        else:
            self.theme = getattr(config, "theme", "dark")

        self.setWindowTitle("Organize Album Files")
        self.setModal(True)
        self.resize(1060, 640)
        self.setMinimumSize(780, 480)

        self._build_ui()
        self.apply_theme(self.theme)
        self._rebuild_plan()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _make_pane(self, header_text: str) -> QTableWidget:
        table = QTableWidget(0, 1)
        table.setHorizontalHeaderLabels([header_text])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Keep the file name readable even if the pane has to truncate a path.
        table.setTextElideMode(Qt.TextElideMode.ElideLeft)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)
        table.setShowGrid(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        # Fill the pane so no white/empty strip appears next to short paths.
        header.setStretchLastSection(True)
        # Wide columns would otherwise centre the header off-screen.
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        return table

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        album = self.tracks[0].get("album", "") if self.tracks else ""
        artist = self.tracks[0].get("album_artist", "") if self.tracks else ""
        self.title_lbl = QLabel(f"Organize “{escape(str(album))}” — {escape(str(artist))}")
        self.title_lbl.setObjectName("organizeTitle")
        layout.addWidget(self.title_lbl)

        # Library root selector
        root_row = QHBoxLayout()
        root_row.setSpacing(10)
        root_label = QLabel("Library:")
        root_label.setMinimumWidth(70)
        root_row.addWidget(root_label)

        self.root_combo = QComboBox()
        for root in self.library_roots:
            self.root_combo.addItem(root, root)
        index = self.root_combo.findData(self.default_root)
        self.root_combo.setCurrentIndex(max(0, index))
        self.root_combo.currentIndexChanged.connect(self._rebuild_plan)
        root_row.addWidget(self.root_combo, 1)
        layout.addLayout(root_row)

        self.destination_lbl = QLabel("")
        self.destination_lbl.setObjectName("organizeHint")
        self.destination_lbl.setWordWrap(True)
        layout.addWidget(self.destination_lbl)

        # View options: compact "differences only" vs full paths.
        options_row = QHBoxLayout()
        options_row.setSpacing(12)
        self.show_diff_cb = QCheckBox("Show only differences")
        self.show_diff_cb.setChecked(True)
        self.show_diff_cb.setToolTip(
            "Checked: hide the shared path prefix and rows that need no change.\n"
            "Unchecked: show full paths for every track."
        )
        self.show_diff_cb.toggled.connect(self._render_rows)
        options_row.addWidget(self.show_diff_cb)

        self.prefix_lbl = QLabel("")
        self.prefix_lbl.setObjectName("organizeHint")
        self.prefix_lbl.setWordWrap(True)
        options_row.addWidget(self.prefix_lbl, 1)
        layout.addLayout(options_row)

        # Two independent panes: each has its own horizontal scrollbar.
        panes = QHBoxLayout()
        panes.setSpacing(10)
        self.left_table = self._make_pane("Current location")
        self.right_table = self._make_pane("After organizing")
        self.left_table.verticalScrollBar().setVisible(False)
        self.left_table.verticalScrollBar().valueChanged.connect(self._on_left_scrolled)
        self.right_table.verticalScrollBar().valueChanged.connect(self._on_right_scrolled)
        panes.addWidget(self.left_table, 1)
        panes.addWidget(self.right_table, 1)
        layout.addLayout(panes, 1)

        # Backwards-compatible alias: older code/tests refer to ``dlg.table``.
        self.table = self.left_table

        self.summary_lbl = QLabel("")
        self.summary_lbl.setObjectName("organizeSummary")
        self.summary_lbl.setWordWrap(True)
        layout.addWidget(self.summary_lbl)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self.btn_cancel)

        self.btn_apply = QPushButton("Organize files")
        self.btn_apply.setObjectName("organizeApply")
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self.accept)
        buttons.addWidget(self.btn_apply)
        layout.addLayout(buttons)

    def _on_left_scrolled(self, value: int):
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self.right_table.verticalScrollBar().setValue(value)
        self._syncing_scroll = False

    def _on_right_scrolled(self, value: int):
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self.left_table.verticalScrollBar().setValue(value)
        self._syncing_scroll = False

    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = theme == "light"
        if is_light:
            self.setStyleSheet("""
                QDialog { background-color: #f6f8fa; color: #1f2328; }
                QLabel { color: #1f2328; }
                QLabel#organizeTitle { font-size: 14px; font-weight: 700; color: #0969da; }
                QLabel#organizeHint { color: #57606a; font-size: 12px; }
                QLabel#organizeSummary { color: #57606a; font-size: 12px; }
                QCheckBox { color: #1f2328; font-size: 12px; }
                QCheckBox::indicator {
                    width: 14px; height: 14px; border: 1px solid #d0d7de;
                    border-radius: 3px; background-color: #ffffff;
                }
                QCheckBox::indicator:checked { background-color: #0969da; border-color: #0969da; }
                QTableWidget {
                    background-color: #ffffff;
                    alternate-background-color: #f6f8fa;
                    color: #1f2328;
                    border: 1px solid #d0d7de;
                    border-radius: 6px;
                }
                QHeaderView::section {
                    background-color: #eaeef2;
                    color: #57606a;
                    border: none;
                    border-bottom: 1px solid #d0d7de;
                    padding: 6px 8px;
                    font-weight: 600;
                }
                QComboBox {
                    background-color: #ffffff; color: #1f2328;
                    border: 1px solid #d0d7de; border-radius: 6px; padding: 6px 10px;
                }
                QComboBox QAbstractItemView {
                    background-color: #ffffff; color: #1f2328;
                    selection-background-color: #0969da; selection-color: #ffffff;
                }
                QPushButton {
                    background-color: #ffffff; color: #1f2328;
                    border: 1px solid #d0d7de; border-radius: 6px;
                    padding: 7px 18px; font-weight: 500;
                }
                QPushButton:hover { background-color: #eaeef2; }
                QPushButton#organizeApply {
                    background-color: #1f883d; color: #ffffff; border: none; font-weight: 600;
                }
                QPushButton#organizeApply:hover { background-color: #1a7f37; }
            """)
        else:
            self.setStyleSheet("""
                QDialog { background-color: #0d1117; color: #c9d1d9; }
                QLabel { color: #c9d1d9; }
                QLabel#organizeTitle { font-size: 14px; font-weight: 700; color: #58a6ff; }
                QLabel#organizeHint { color: #8b949e; font-size: 12px; }
                QLabel#organizeSummary { color: #8b949e; font-size: 12px; }
                QCheckBox { color: #c9d1d9; font-size: 12px; }
                QCheckBox::indicator {
                    width: 14px; height: 14px; border: 1px solid #30363d;
                    border-radius: 3px; background-color: #0d1117;
                }
                QCheckBox::indicator:checked { background-color: #238636; border-color: #238636; }
                QTableWidget {
                    background-color: #161b22;
                    alternate-background-color: #12171e;
                    color: #c9d1d9;
                    border: 1px solid #30363d;
                    border-radius: 6px;
                }
                QHeaderView::section {
                    background-color: #21262d;
                    color: #8b949e;
                    border: none;
                    border-bottom: 1px solid #30363d;
                    padding: 6px 8px;
                    font-weight: 600;
                }
                QComboBox {
                    background-color: #0d1117; color: #c9d1d9;
                    border: 1px solid #30363d; border-radius: 6px; padding: 6px 10px;
                }
                QComboBox QAbstractItemView {
                    background-color: #161b22; color: #c9d1d9;
                    selection-background-color: #1f6feb; selection-color: #ffffff;
                }
                QPushButton {
                    background-color: #21262d; color: #c9d1d9;
                    border: 1px solid #30363d; border-radius: 6px;
                    padding: 7px 18px; font-weight: 500;
                }
                QPushButton:hover { background-color: #30363d; }
                QPushButton#organizeApply {
                    background-color: #238636; color: #ffffff; border: none; font-weight: 600;
                }
                QPushButton#organizeApply:hover { background-color: #2ea043; }
            """)

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------
    def chosen_library(self) -> str:
        return self.root_combo.currentData() or self.default_root

    def plan(self) -> List[Dict[str, Any]]:
        return self._plan

    @staticmethod
    def _split_common_prefix(src: str, dst: str):
        """Returns (src_tail, dst_tail) starting at the first differing path segment."""
        if not src or not dst:
            return src, dst
        limit = min(len(src), len(dst))
        index = 0
        while index < limit and src[index] == dst[index]:
            index += 1
        if index == 0:
            return src, dst
        # Do not cut in the middle of a path segment.
        cut = max(src.rfind("/", 0, index), src.rfind("\\", 0, index)) + 1
        if cut <= 0:
            cut = index
        return src[cut:], dst[cut:]

    def _common_prefix(self) -> str:
        prefixes = []
        for item in self._plan:
            src = str(item["src"])
            dst = str(item["dst"])
            limit = min(len(src), len(dst))
            index = 0
            while index < limit and src[index] == dst[index]:
                index += 1
            cut = max(src.rfind("/", 0, index), src.rfind("\\", 0, index)) + 1
            prefixes.append(src[:cut] if cut > 0 else "")
        if not prefixes:
            return ""
        common = prefixes[0]
        for value in prefixes[1:]:
            while common and not value.startswith(common):
                common = common[:-1]
        if common and not common.endswith(("/", "\\")):
            cut = max(common.rfind("/"), common.rfind("\\")) + 1
            common = common[:cut]
        return common

    def _fill_pane(self, table: QTableWidget, texts: List[tuple], show_changed: List[bool]):
        """texts: list of (visible_text, full_text, tooltip) per row."""
        table.setRowCount(len(texts))
        for row, (value, tooltip) in enumerate(texts):
            item = QTableWidgetItem(value)
            item.setToolTip(tooltip)
            if not show_changed[row]:
                item.setForeground(Qt.GlobalColor.gray)
            table.setItem(row, 0, item)
        table.resizeColumnsToContents()

    def _render_rows(self):
        if not hasattr(self, "left_table"):
            return
        diff_only = self.show_diff_cb.isChecked()
        prefix = self._common_prefix() if diff_only else ""
        self.prefix_lbl.setText(
            f"Common prefix hidden: <code>{escape(prefix)}</code>" if prefix else ""
        )

        visible = [item for item in self._plan if item["changed"] or not diff_only]

        left_rows = []
        right_rows = []
        changed_flags = []
        for item in visible:
            src_full = str(item["src"])
            dst_full = str(item["dst"])
            changed = bool(item["changed"])
            if diff_only and changed:
                src_text, dst_text = self._split_common_prefix(src_full, dst_full)
            else:
                src_text, dst_text = src_full, dst_full
            if not changed:
                dst_text = "already in place"
            left_rows.append((src_text, src_full))
            right_rows.append((dst_text, dst_full))
            changed_flags.append(changed)

        self._fill_pane(self.left_table, left_rows, changed_flags)
        self._fill_pane(self.right_table, right_rows, changed_flags)

    def _rebuild_plan(self):
        root = self.chosen_library()
        self._plan = build_organization_plan(root, self.tracks, self.template)

        changed = sum(1 for item in self._plan if item["changed"])
        self._render_rows()

        album = self.tracks[0].get("album", "") if self.tracks else ""
        artist = self.tracks[0].get("album_artist", "") if self.tracks else ""
        year = self.tracks[0].get("year", "") if self.tracks else ""
        target_dir = Path(root) / artist / f"{year} - {album}"
        self.destination_lbl.setText(
            f"Template: <code>{escape(self.template)}</code> &nbsp;·&nbsp; "
            f"destination: <code>{escape(str(target_dir))}</code>"
        )
        self.summary_lbl.setText(
            f"{changed} of {len(self._plan)} file(s) will be renamed or moved."
            if changed
            else "Everything is already in place — nothing to do."
        )
        self.btn_apply.setText(f"Organize {changed} file(s)" if changed else "Organize files")
        self.btn_apply.setEnabled(changed > 0)
