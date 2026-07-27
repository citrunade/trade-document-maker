"""
全局界面样式（QSS + QPalette），支持浅色/深色两套主题。

问题背景：如果只设置 QSS 而不设置 QPalette，当 Windows 系统处于深色模式时，
部分原生控件（如消息弹窗、下拉列表、日历弹出框）会跟随系统深色调色板渲染，
而 QSS 覆盖到的控件仍是浅色，导致界面出现"一半浅一半深"的撞色/花屏观感。
解决方式：应用内提供独立于系统设置的主题开关，同时设置 QPalette 与 QSS，
确保所有控件（包括原生弹窗）风格一致，不再依赖/跟随系统的深色模式设置。
"""
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt

ACCENT = "#5B9BD5"
ACCENT_DARK = "#4A82BE"

_THEMES = {
    "light": {
        "accent": "#5B9BD5",
        "accent_dark": "#4A82BE",
        "accent_pressed": "#3D6B9C",
        "accent_disabled": "#B9C4CE",
        "accent_light": "#EAF2FB",
        "border": "#D5DCE3",
        "text": "#2C3E50",
        "text_muted": "#5A6B7A",
        "text_hint": "#96A2AC",
        "window_bg": "#F5F7FA",
        "surface_bg": "#FFFFFF",
        "tab_bg": "#E9EEF3",
        "tab_hover": "#F0F4F8",
        "row_alt": "#EAF2FB",
        "grid_line": "#EEF1F4",
        "header_border": "#7DAEE0",
    },
    "dark": {
        "accent": "#5B9BD5",
        "accent_dark": "#6FAEE8",
        "accent_pressed": "#3D6B9C",
        "accent_disabled": "#3C4650",
        "accent_light": "#2A3644",
        "border": "#3E4A56",
        "text": "#E4E9EE",
        "text_muted": "#AEB9C4",
        "text_hint": "#7C8894",
        "window_bg": "#1E242B",
        "surface_bg": "#262E37",
        "tab_bg": "#232B33",
        "tab_hover": "#2C3540",
        "row_alt": "#2A3441",
        "grid_line": "#333E48",
        "header_border": "#4A82BE",
    },
}


def _build_stylesheet(c: dict) -> str:
    return f"""
QWidget {{
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {c['text']};
}}

QMainWindow {{
    background-color: {c['window_bg']};
}}

QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: 4px;
    background: {c['surface_bg']};
    top: -1px;
}}

QTabBar::tab {{
    background: {c['tab_bg']};
    border: 1px solid {c['border']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 18px;
    margin-right: 2px;
    color: {c['text_muted']};
}}

QTabBar::tab:selected {{
    background: {c['surface_bg']};
    color: {c['accent_dark']};
    font-weight: 600;
    border-bottom: 2px solid {c['accent']};
}}

QTabBar::tab:hover:!selected {{
    background: {c['tab_hover']};
}}

QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
    background: {c['surface_bg']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {c['accent_dark']};
}}

QPushButton {{
    background-color: {c['accent']};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {c['accent_dark']};
}}

QPushButton:pressed {{
    background-color: {c['accent_pressed']};
}}

QPushButton:disabled {{
    background-color: {c['accent_disabled']};
}}

QLineEdit, QTextEdit, QDateEdit, QComboBox, QDoubleSpinBox {{
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 6px;
    background: {c['surface_bg']};
    color: {c['text']};
    selection-background-color: {c['accent']};
}}

QLineEdit:focus, QTextEdit:focus, QDateEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {c['accent']};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background: {c['surface_bg']};
    color: {c['text']};
    selection-background-color: {c['accent']};
    selection-color: white;
    border: 1px solid {c['border']};
}}

QTableWidget {{
    border: 1px solid {c['border']};
    border-radius: 4px;
    gridline-color: {c['grid_line']};
    background: {c['surface_bg']};
    alternate-background-color: {c['row_alt']};
    selection-background-color: {c['accent']};
    selection-color: white;
}}

QHeaderView::section {{
    background-color: {c['accent']};
    color: white;
    padding: 6px;
    border: none;
    border-right: 1px solid {c['header_border']};
    font-weight: 600;
}}

QListWidget {{
    border: 1px solid {c['border']};
    border-radius: 4px;
    background: {c['surface_bg']};
}}

QListWidget::item:selected {{
    background: {c['accent']};
    color: white;
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

QStatusBar {{
    background: {c['tab_bg']};
    color: {c['accent_dark']};
    font-weight: 500;
}}

QMessageBox {{
    background: {c['surface_bg']};
}}

QCalendarWidget QWidget {{
    background: {c['surface_bg']};
    color: {c['text']};
}}

QCalendarWidget QAbstractItemView:enabled {{
    background: {c['surface_bg']};
    color: {c['text']};
    selection-background-color: {c['accent']};
    selection-color: white;
}}
"""


def _build_palette(c: dict) -> QPalette:
    """
    显式设置调色板，让 QMessageBox / 下拉列表 / 日历弹窗等原生控件
    也遵循应用内主题，而不是跟随 Windows 系统的深色模式设置。
    """
    palette = QPalette()
    window = QColor(c["window_bg"])
    surface = QColor(c["surface_bg"])
    text = QColor(c["text"])
    accent = QColor(c["accent"])

    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, surface)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["row_alt"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, surface)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, surface)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, accent)
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["text_hint"]))
    return palette


def apply_theme(app, theme: str = "light") -> None:
    """theme: "light" 或 "dark"。与操作系统深色模式设置完全独立，切换后立即生效。"""
    colors = _THEMES.get(theme, _THEMES["light"])
    app.setPalette(_build_palette(colors))
    app.setStyleSheet(_build_stylesheet(colors))
