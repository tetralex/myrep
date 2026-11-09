"""Suchergebnisse und Schnellsuche (Strg+K)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)

from ..widgets import AppContext, Page, muted

KIND_ICON = {"article": "📄", "glossary": "📖", "note": "📝", "refrigerant": "🧊", "fault": "🩺"}


def fill_results(lst: QListWidget, hits, empty_text: str) -> None:
    lst.clear()
    for h in hits:
        snippet = h.snippet.replace("«", "").replace("»", "")
        it = QListWidgetItem(f"{KIND_ICON.get(h.kind, '•')}  {h.title}    ·  {h.kind_label}\n      {snippet[:140]}")
        it.setData(Qt.UserRole, (h.kind, h.ref_id))
        lst.addItem(it)
    if not hits:
        it = QListWidgetItem(empty_text)
        it.setFlags(Qt.NoItemFlags)
        lst.addItem(it)


class SearchPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, "🔍 Suche")
        self.input = QLineEdit()
        self.input.setObjectName("SearchBig")
        self.input.setPlaceholderText("Suchbegriff …")
        self.root.addWidget(self.input)
        self.count = muted("")
        self.root.addWidget(self.count)
        self.list = QListWidget()
        self.list.itemActivated.connect(self._open)
        self.list.itemClicked.connect(self._open)
        self.root.addWidget(self.list, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._run)
        self.input.textChanged.connect(self._timer.start)

    def search(self, text: str) -> None:
        self.input.setText(text)
        self._run()
        self.input.setFocus()

    def _run(self) -> None:
        text = self.input.text().strip()
        hits = self.db.search(text, limit=100) if text else []
        self.count.setText(f"{len(hits)} Treffer" if text else "")
        fill_results(self.list, hits, "Nix gefunden – probier's mal mit einem anderen Begriff 🧊" if text else "")

    def _open(self, item) -> None:
        data = item.data(Qt.UserRole)
        if data:
            self.ctx.navigate.emit(data[0], int(data[1]))


class QuickSearch(QDialog):
    """Spotlight-artige Schnellsuche."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.ctx = ctx
        self.setModal(True)
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.input = QLineEdit()
        self.input.setObjectName("SearchBig")
        self.input.setPlaceholderText("🔍  Schnellsuche – Artikel, Kältemittel, Glossar, Fehler, Notizen …")
        lay.addWidget(self.input)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        lay.addWidget(QLabel("↑↓ auswählen · Enter öffnen · Esc schließen"))
        self.input.textChanged.connect(self._run)
        self.input.returnPressed.connect(self._open_current)
        self.list.itemActivated.connect(self._open)
        self.list.itemClicked.connect(self._open)
        self.setStyleSheet("QDialog { border: 2px solid #3BA7F0; border-radius: 16px; }")

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up) and self.list.count():
            row = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return
        super().keyPressEvent(e)

    def _run(self, text: str) -> None:
        hits = self.ctx.db.search(text, limit=20) if text.strip() else []
        fill_results(self.list, hits, "Nix gefunden 🧊" if text.strip() else "")
        if hits:
            self.list.setCurrentRow(0)

    def _open_current(self) -> None:
        it = self.list.currentItem()
        if it:
            self._open(it)

    def _open(self, item) -> None:
        data = item.data(Qt.UserRole)
        if data:
            self.accept()
            self.ctx.navigate.emit(data[0], int(data[1]))
