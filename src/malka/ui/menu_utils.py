"""Shared context-menu styling for widgets that carry their own stylesheet.

A QMenu inherits the stylesheet of its nearest styled parent widget.  Track rows
apply a local stylesheet, so they cannot rely on the MainWindow stylesheet for
the context menu.  This helper keeps those menus identical to the rest of the
application in both themes.
"""


def context_menu_qss(theme: str) -> str:
    light = theme == "light"
    background = "#ffffff" if light else "#1a1e24"
    foreground = "#1f2328" if light else "#e6edf3"
    border = "#d0d7de" if light else "#30363d"
    hover = "#f3f4f6" if light else "#262c36"
    accent = "#0969da" if light else "#58a6ff"
    disabled = "#8c959f" if light else "#6e7681"

    return f"""
        QMenu {{
            background-color: {background};
            color: {foreground};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 7px 26px 7px 36px;
            border-radius: 6px;
        }}
        QMenu::icon {{
            left: 9px;
            width: 20px;
            height: 20px;
        }}
        QMenu::item:selected {{
            background-color: {hover};
            color: {accent};
        }}
        QMenu::item:disabled {{
            color: {disabled};
        }}
        QMenu::separator {{
            height: 1px;
            background: {border};
            margin: 5px 8px;
        }}
    """
