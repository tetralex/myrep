"""Helles und dunkles Theme (QSS)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtCore import Qt

from ..config import ACCENT, ACCENT_2, resource_path

LIGHT = dict(
    bg="#F4F7FB", surface="#FFFFFF", surface2="#EEF3F9", border="#DCE4EE",
    text="#16212E", muted="#5E6B7A", sidebar="#FFFFFF", hover="#E6F2FD",
    selected="#D6EBFC", input="#FFFFFF", code="#EEF3F9",
)
DARK = dict(
    bg="#0F1620", surface="#17212D", surface2="#1E2A38", border="#2A3949",
    text="#E6EEF6", muted="#93A3B5", sidebar="#131C27", hover="#1F3247",
    selected="#1D3D5C", input="#1B2633", code="#1E2A38",
)


def system_prefers_dark() -> bool:
    try:
        hints = QGuiApplication.styleHints()
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def colors(dark: bool) -> dict[str, str]:
    c = dict(DARK if dark else LIGHT)
    c["accent"] = ACCENT
    c["accent2"] = ACCENT_2
    return c


def stylesheet(dark: bool, font_size: int = 11) -> str:
    c = colors(dark)
    fs = font_size
    up = resource_path("assets/arrow_up.png").as_posix()
    down = resource_path("assets/arrow_down.png").as_posix()
    return f"""
* {{
    font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif;
    font-size: {fs}pt;
    color: {c['text']};
}}
QMainWindow, QDialog, QWidget#Page {{ background: {c['bg']}; }}
QWidget#Sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['border']}; }}
QLabel#AppTitle {{ font-size: {fs + 6}pt; font-weight: 700; color: {c['accent']}; padding: 6px 4px; }}
QLabel#AppSub {{ color: {c['muted']}; font-size: {fs - 1}pt; padding: 0 4px 10px 4px; }}
QLabel#PageTitle {{ font-size: {fs + 10}pt; font-weight: 700; }}
QLabel#PageSub {{ color: {c['muted']}; font-size: {fs + 1}pt; }}
QLabel#SectionTitle {{ font-size: {fs + 3}pt; font-weight: 600; padding-top: 6px; }}
QLabel#Muted {{ color: {c['muted']}; }}
QLabel#Big {{ font-size: {fs + 14}pt; font-weight: 700; color: {c['accent']}; }}
QLabel#Hero {{ font-size: {fs + 16}pt; font-weight: 700; }}

QListWidget#Nav {{ background: transparent; border: none; outline: 0; }}
QListWidget#Nav::item {{ padding: 11px 12px; margin: 2px 6px; border-radius: 10px; }}
QListWidget#Nav::item:hover {{ background: {c['hover']}; }}
QListWidget#Nav::item:selected {{ background: {c['selected']}; color: {c['text']}; font-weight: 600; }}

QFrame#Card {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px;
}}
QFrame#Card:hover {{ border-color: {c['accent']}; }}
QFrame#AccentCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['accent']}, stop:1 {c['accent2']});
    border-radius: 18px;
}}
QFrame#AccentCard QLabel {{ color: white; }}
QFrame#DropZone {{
    background: {c['surface']}; border: 2px dashed {c['accent']}; border-radius: 18px;
}}
QFrame#DropZone[active="true"] {{ background: {c['hover']}; }}

QPushButton {{
    background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 10px;
    padding: 8px 16px; min-height: 22px;
}}
QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['selected']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#Primary {{ background: {c['accent']}; color: white; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #2C93D9; }}
QPushButton#Danger {{ color: #EF4444; }}
QPushButton#Chip {{ border-radius: 14px; padding: 4px 12px; font-size: {fs - 1}pt; }}
QToolButton {{ border: none; border-radius: 8px; padding: 6px; background: transparent; }}
QToolButton:hover {{ background: {c['hover']}; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c['input']}; border: 1px solid {c['border']}; border-radius: 10px;
    padding: 7px 10px; selection-background-color: {c['accent']}; selection-color: white;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QDoubleSpinBox:focus, QSpinBox:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit#SearchBig {{ font-size: {fs + 4}pt; padding: 14px 18px; border-radius: 16px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 10px; height: 6px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 26px; border: none; background: transparent;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 10px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 10px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {c['hover']}; }}
QAbstractSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 6px; }}
QAbstractSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border']};
    selection-background-color: {c['selected']}; selection-color: {c['text']}; }}

QTextBrowser {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px; padding: 14px; }}

QTreeWidget, QListWidget, QTableWidget, QTableView {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px;
    alternate-background-color: {c['surface2']}; outline: 0;
}}
QTreeWidget::item, QListWidget::item {{ padding: 6px 4px; border-radius: 6px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {c['hover']}; }}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {{
    background: {c['selected']}; color: {c['text']};
}}
QHeaderView::section {{
    background: {c['surface2']}; border: none; border-bottom: 1px solid {c['border']};
    padding: 8px; font-weight: 600;
}}
QTableWidget {{ gridline-color: {c['border']}; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; padding: 9px 16px; margin-right: 4px; border-radius: 10px;
    color: {c['muted']};
}}
QTabBar::tab:selected {{ background: {c['selected']}; color: {c['text']}; font-weight: 600; }}
QTabBar::tab:hover {{ background: {c['hover']}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QSplitter::handle {{ background: transparent; width: 8px; }}
QProgressBar {{ border: 1px solid {c['border']}; border-radius: 8px; text-align: center; background: {c['surface2']}; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 7px; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; padding: 6px; border-radius: 10px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['selected']}; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: 12px; margin-top: 14px; padding: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; font-weight: 600; }}
"""


def markdown_css(dark: bool) -> str:
    c = colors(dark)
    return f"""
h1, h2, h3 {{ color: {c['accent']}; }}
table {{ border-collapse: collapse; }}
th {{ background: {c['surface2']}; }}
td, th {{ padding: 6px 10px; border: 1px solid {c['border']}; }}
code {{ background: {c['code']}; }}
blockquote {{ color: {c['muted']}; }}
a {{ color: {c['accent']}; }}
"""


def apply_palette(app, dark: bool) -> None:
    c = colors(dark)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(c["bg"]))
    pal.setColor(QPalette.WindowText, QColor(c["text"]))
    pal.setColor(QPalette.Base, QColor(c["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(c["surface2"]))
    pal.setColor(QPalette.Text, QColor(c["text"]))
    pal.setColor(QPalette.Button, QColor(c["surface2"]))
    pal.setColor(QPalette.ButtonText, QColor(c["text"]))
    pal.setColor(QPalette.Highlight, QColor(c["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.Link, QColor(c["accent"]))
    pal.setColor(QPalette.PlaceholderText, QColor(c["muted"]))
    pal.setColor(QPalette.ToolTipBase, QColor(c["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(c["text"]))
    app.setPalette(pal)
