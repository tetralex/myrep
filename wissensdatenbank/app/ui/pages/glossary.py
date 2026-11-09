"""Glossar A–Z."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from ..widgets import AppContext, Page, confirm, hbox, muted, warn


class GlossaryEditor(QDialog):
    def __init__(self, ctx: AppContext, gid: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.gid = gid
        self.setWindowTitle("Begriff bearbeiten" if gid else "Neuer Begriff")
        self.resize(560, 360)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.term = QLineEdit()
        self.definition = QTextEdit()
        self.article = QComboBox()
        self.article.addItem("— kein Artikel —", None)
        for a in ctx.db.articles():
            self.article.addItem(a["title"], a["id"])
        form.addRow("Begriff", self.term)
        form.addRow("Erklärung", self.definition)
        form.addRow("Mehr dazu in", self.article)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Speichern")
        bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if gid:
            g = ctx.db.glossary_entry(gid)
            self.term.setText(g["term"])
            self.definition.setPlainText(g["definition"])
            idx = self.article.findData(g["article_id"])
            self.article.setCurrentIndex(max(idx, 0))

    def _save(self) -> None:
        if not self.term.text().strip():
            warn(self, "Begriff fehlt", "Bitte einen Begriff eingeben.")
            return
        self.ctx.db.save_glossary(self.term.text(), self.definition.toPlainText(), self.article.currentData(), self.gid)
        self.ctx.notify("glossary")
        self.accept()


class GlossaryPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, "📖 Glossar", "Fachbegriffe von A bis Z – kurz und knackig erklärt.")
        self.current: int | None = None
        self.letter: str | None = None
        letters = QHBoxLayout()
        letters.setSpacing(4)
        self.letter_buttons = []
        for ch in ["Alle"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]:
            b = QPushButton(ch)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, l=ch: self._set_letter(None if l == "Alle" else l))
            letters.addWidget(b)
            self.letter_buttons.append(b)
        letters.addStretch(1)
        self.root.addLayout(letters)

        split = QSplitter(Qt.Horizontal)
        self.root.addWidget(split, 1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("🔍 Begriff suchen …")
        self.filter.textChanged.connect(self.refresh)
        ll.addWidget(self.filter)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda it, _p: self.show_entry(it.data(Qt.UserRole)) if it else None)
        ll.addWidget(self.list, 1)
        add = QPushButton("＋ Begriff")
        add.clicked.connect(lambda: GlossaryEditor(self.ctx, None, self).exec())
        ll.addWidget(add)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        self.term = QLabel("Begriff auswählen 👈")
        self.term.setObjectName("Big")
        self.term.setWordWrap(True)
        self.definition = QLabel()
        self.definition.setWordWrap(True)
        self.definition.setStyleSheet("font-size: 13pt;")
        self.more = QPushButton()
        self.more.setVisible(False)
        self.more.clicked.connect(self._open_article)
        self.btn_edit = QPushButton("✏️ Bearbeiten")
        self.btn_del = QPushButton("🗑")
        self.btn_del.setObjectName("Danger")
        self.btn_edit.clicked.connect(lambda: GlossaryEditor(self.ctx, self.current, self).exec())
        self.btn_del.clicked.connect(self._delete)
        rl.addWidget(self.term)
        rl.addWidget(self.definition)
        rl.addLayout(hbox(self.more, None))
        rl.addLayout(hbox(self.btn_edit, self.btn_del, None))
        rl.addStretch(1)
        rl.addWidget(muted("Tipp: Neue Begriffe kannst du auch als CSV (Begriff;Erklärung) unter „Wissen importieren“ einspielen."))
        split.addWidget(right)
        split.setSizes([360, 800])
        self.btn_edit.setEnabled(False)
        self.btn_del.setEnabled(False)
        ctx.changed.connect(lambda k: self.refresh() if k in ("glossary", "all") else None)
        self._set_letter(None)

    def _set_letter(self, letter: str | None) -> None:
        self.letter = letter
        for b in self.letter_buttons:
            b.setChecked(b.text() == (letter or "Alle"))
        self.refresh()

    def refresh(self) -> None:
        flt = self.filter.text().strip().lower()
        self.list.blockSignals(True)
        self.list.clear()
        for g in self.db.glossary():
            first = g["term"][:1].upper().replace("Ä", "A").replace("Ö", "O").replace("Ü", "U")
            if self.letter and first != self.letter:
                continue
            if flt and flt not in g["term"].lower() and flt not in g["definition"].lower():
                continue
            it = QListWidgetItem(g["term"])
            it.setData(Qt.UserRole, g["id"])
            self.list.addItem(it)
            if g["id"] == self.current:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.current and self.db.glossary_entry(self.current):
            self.show_entry(self.current)

    def show_entry(self, gid: int) -> None:
        g = self.db.glossary_entry(gid)
        if not g:
            return
        self.current = gid
        self.term.setText(g["term"])
        self.definition.setText(g["definition"])
        a = self.db.article(g["article_id"]) if g["article_id"] else None
        self.more.setVisible(bool(a))
        if a:
            self.more.setText(f"📄 Mehr dazu: {a['title']}")
            self.more.setProperty("article_id", a["id"])
        self.btn_edit.setEnabled(True)
        self.btn_del.setEnabled(True)

    def _open_article(self) -> None:
        aid = self.more.property("article_id")
        if aid:
            self.ctx.navigate.emit("article", int(aid))

    def _delete(self) -> None:
        g = self.db.glossary_entry(self.current) if self.current else None
        if g and confirm(self, "Löschen", f"Begriff „{g['term']}“ löschen?"):
            self.db.delete_glossary(g["id"])
            self.current = None
            self.term.setText("Begriff auswählen 👈")
            self.definition.setText("")
            self.more.setVisible(False)
            self.ctx.notify("glossary")
