"""Gemeinsame Bausteine der Oberfläche."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QTextDocument
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QMessageBox, QPushButton, QSizePolicy,
    QTextBrowser, QVBoxLayout, QWidget,
)

from ..core.db import Database


class AppContext(QObject):
    """Gemeinsamer Zustand: Datenbank + Signale für Aktualisierungen."""
    changed = Signal(str)                 # "article", "glossary", "note", "refrigerant", "fault", "all"
    navigate = Signal(str, int)           # (kind, id) – Treffer öffnen
    open_page = Signal(str)               # Seiten-Schlüssel
    theme_changed = Signal(bool)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.dark = False

    def notify(self, kind: str = "all") -> None:
        self.changed.emit(kind)


def page_header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 8)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("PageSub")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


class Page(QWidget):
    def __init__(self, ctx: AppContext, title: str = "", subtitle: str = ""):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Page")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 22, 28, 22)
        self.root.setSpacing(12)
        if title:
            self.root.addWidget(page_header(title, subtitle))

    @property
    def db(self) -> Database:
        return self.ctx.db

    def refresh(self) -> None:  # von Unterklassen überschrieben
        pass


class Card(QFrame):
    clicked = Signal()

    def __init__(self, title: str = "", icon: str = "", parent: QWidget | None = None, clickable: bool = False):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(18, 16, 18, 16)
        self.lay.setSpacing(8)
        self._clickable = clickable
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
        if title:
            t = QLabel(f"{icon}  {title}" if icon else title)
            t.setObjectName("SectionTitle")
            self.lay.addWidget(t)

    def mouseReleaseEvent(self, event):
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class LinkButton(QPushButton):
    """Flacher Knopf für Listen auf der Startseite."""

    def __init__(self, text: str, callback: Callable[[], None]):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("text-align: left; border: none; background: transparent; padding: 6px 4px;")
        self.clicked.connect(callback)


class MarkdownView(QTextBrowser):
    """Zeigt Markdown an. Links: http(s) → Browser, artikel:Titel → Artikel öffnen."""
    article_link = Signal(str)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_link)
        self.setSearchPaths([str(ctx.db.attachments_dir)])

    def set_markdown(self, text: str) -> None:
        from .theme import markdown_css
        self.document().setDefaultStyleSheet(markdown_css(self.ctx.dark))
        self.setMarkdown(text)

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() == "artikel":
            self.article_link.emit(url.toString()[len("artikel:"):])
        elif url.scheme() in ("http", "https", "mailto", "file"):
            QDesktopServices.openUrl(url)
        else:
            path = Path(self.ctx.db.attachments_dir) / url.toString()
            if path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def info(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def warn(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def confirm(parent: QWidget, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: rgba(127,127,127,0.25);")
    return f


def muted(text: str, wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(wrap)
    return lbl


def markdown_to_pdf(markdown: str, title: str, target: str, css: str = "") -> None:
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter
    from PySide6.QtCore import QMarginsF
    doc = QTextDocument()
    doc.setDefaultStyleSheet(css)
    doc.setDefaultFont(QFont("Segoe UI", 10))
    doc.setMarkdown(f"# {title}\n\n{markdown}")
    writer = QPdfWriter(target)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(18, 18, 18, 18), QPageLayout.Millimeter)
    writer.setTitle(title)
    doc.print_(writer)


class FlowLayout(QLayout):
    """Zeilenumbrechendes Layout für Tag-Chips."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for item in self._items:
            w = item.sizeHint().width()
            if x + w > rect.right() and line_h > 0:
                x = rect.x()
                y += line_h + sp
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x += w + sp
            line_h = max(line_h, item.sizeHint().height())
        return y + line_h - rect.y()

    def clear(self):
        while self._items:
            item = self._items.pop()
            if item.widget():
                item.widget().deleteLater()


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def hbox(*widgets, spacing: int = 8, stretch_end: bool = False) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, QLayout):
            lay.addLayout(w)
        elif w is None:
            lay.addStretch(1)
        else:
            lay.addWidget(w)
    if stretch_end:
        lay.addStretch(1)
    return lay


def expanding(widget: QWidget) -> QWidget:
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return widget
