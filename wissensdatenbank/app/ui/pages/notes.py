"""Eigene Notizen & Baustellen-Log."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ...core.importer import IMAGE_EXT
from ..widgets import AppContext, Page, confirm, hbox, info, muted


class NotesPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, "📝 Notizen & Baustellen-Log", "Schnell notiert: Anlage, Kunde, Messwerte, Fotos.")
        self.current: int | None = None
        split = QSplitter(Qt.Horizontal)
        self.root.addWidget(split, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("🔍 Notizen durchsuchen …")
        self.filter.textChanged.connect(self.refresh)
        ll.addWidget(self.filter)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda it, _p: self.load(it.data(Qt.UserRole)) if it else None)
        ll.addWidget(self.list, 1)
        new = QPushButton("＋ Neue Notiz")
        new.setObjectName("Primary")
        new.clicked.connect(self.new)
        ll.addWidget(new)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("z. B. Service Kühlraum Metzgerei Huber")
        self.site = QLineEdit()
        self.site.setPlaceholderText("Anlage / Standort")
        self.customer = QLineEdit()
        self.refrigerant = QComboBox()
        self.refrigerant.setEditable(True)
        self.article = QComboBox()
        self.measure = QPlainTextEdit()
        self.measure.setPlaceholderText("Messwerte, z. B.\nND 2,1 bar(ü) / HD 14,8 bar(ü)\nÜberhitzung 6 K, Unterkühlung 4 K")
        self.measure.setMaximumHeight(110)
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText("Was war los? Was wurde gemacht?")
        form.addRow("Titel", self.title)
        form.addRow("Anlage", self.site)
        form.addRow("Kunde", self.customer)
        form.addRow("Kältemittel", self.refrigerant)
        form.addRow("Verknüpfter Artikel", self.article)
        form.addRow("Messwerte", self.measure)
        form.addRow("Notiz", self.body)
        rl.addLayout(form, 1)

        rl.addWidget(QLabel("📷 Fotos & Dateien"))
        self.files = QListWidget()
        self.files.setViewMode(QListWidget.IconMode)
        self.files.setIconSize(QSize(96, 96))
        self.files.setResizeMode(QListWidget.Adjust)
        self.files.setMaximumHeight(150)
        self.files.itemDoubleClicked.connect(self._open_file)
        self.files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._file_menu)
        rl.addWidget(self.files)

        self.meta = muted("")
        save = QPushButton("💾 Speichern")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        add_file = QPushButton("📎 Foto/Datei")
        add_file.clicked.connect(self._add_file)
        to_article = QPushButton("📚 Als Wissensartikel übernehmen")
        to_article.clicked.connect(self._to_article)
        delete = QPushButton("🗑")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete)
        rl.addLayout(hbox(save, add_file, to_article, None, self.meta, delete))
        split.addWidget(right)
        split.setSizes([340, 860])
        ctx.changed.connect(lambda k: self.refresh() if k in ("note", "refrigerant", "article", "all") else None)
        self.refresh()
        self.new()

    def refresh(self) -> None:
        flt = self.filter.text().strip().lower()
        self.list.blockSignals(True)
        self.list.clear()
        for n in self.db.notes():
            hay = " ".join(str(n[k]) for k in ("title", "site", "customer", "refrigerant", "body", "measurements")).lower()
            if flt and flt not in hay:
                continue
            date = n["updated"][:10]
            it = QListWidgetItem(f"📝 {n['title']}\n     {date}  {n['site']}")
            it.setData(Qt.UserRole, n["id"])
            self.list.addItem(it)
            if n["id"] == self.current:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        cur_ref = self.refrigerant.currentText()
        self.refrigerant.clear()
        self.refrigerant.addItem("")
        self.refrigerant.addItems([r["code"] for r in self.db.refrigerants()])
        self.refrigerant.setCurrentText(cur_ref)
        cur_art = self.article.currentData()
        self.article.clear()
        self.article.addItem("— keiner —", None)
        for a in self.db.articles():
            self.article.addItem(a["title"], a["id"])
        idx = self.article.findData(cur_art)
        self.article.setCurrentIndex(max(idx, 0))

    def new(self) -> None:
        self.current = None
        self.list.clearSelection()
        for w in (self.title, self.site, self.customer):
            w.clear()
        self.measure.clear()
        self.body.clear()
        self.refrigerant.setCurrentText("")
        self.article.setCurrentIndex(0)
        self.files.clear()
        self.meta.setText("Neue Notiz")
        self.title.setFocus()

    def load(self, nid: int) -> None:
        n = self.db.note(nid)
        if not n:
            return
        self.current = nid
        self.title.setText(n["title"])
        self.site.setText(n["site"])
        self.customer.setText(n["customer"])
        self.refrigerant.setCurrentText(n["refrigerant"])
        idx = self.article.findData(n["article_id"])
        self.article.setCurrentIndex(max(idx, 0))
        self.measure.setPlainText(n["measurements"])
        self.body.setPlainText(n["body"])
        self.meta.setText(f"erstellt {n['created'][:16].replace('T', ' ')}")
        self._load_files()

    def _load_files(self) -> None:
        self.files.clear()
        if not self.current:
            return
        for att in self.db.attachments(note_id=self.current):
            path = self.db.attachment_path(att)
            it = QListWidgetItem(att["filename"])
            if path.suffix.lower() in IMAGE_EXT:
                pm = QPixmap(str(path))
                if not pm.isNull():
                    it.setIcon(QIcon(pm.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            it.setData(Qt.UserRole, att["id"])
            it.setData(Qt.UserRole + 1, str(path))
            self.files.addItem(it)

    def save(self) -> None:
        self.current = self.db.save_note(
            self.title.text(), self.body.toPlainText(), self.site.text(), self.customer.text(),
            self.refrigerant.currentText(), self.measure.toPlainText(), self.article.currentData(), self.current)
        self.ctx.notify("note")
        self.meta.setText("Gespeichert ✅")

    def _add_file(self) -> None:
        if not self.current:
            self.save()
        paths, _ = QFileDialog.getOpenFileNames(self, "Fotos oder Dateien hinzufügen", "",
                                                "Bilder (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;Alle Dateien (*)")
        for p in paths:
            self.db.add_attachment(p, note_id=self.current)
        self._load_files()

    def _open_file(self, it) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(it.data(Qt.UserRole + 1)))

    def _file_menu(self, pos) -> None:
        it = self.files.itemAt(pos)
        if not it:
            return
        menu = QMenu(self)
        menu.addAction("Öffnen", lambda: self._open_file(it))
        menu.addAction("Entfernen", lambda: (self.db.delete_attachment(it.data(Qt.UserRole)), self._load_files()))
        menu.exec(self.files.mapToGlobal(pos))

    def _to_article(self) -> None:
        self.save()
        n = self.db.note(self.current)
        parts = []
        if n["site"] or n["customer"] or n["refrigerant"]:
            parts.append(" · ".join(x for x in (n["site"], n["customer"], n["refrigerant"]) if x))
        if n["measurements"]:
            parts.append("## Messwerte\n\n```\n" + n["measurements"] + "\n```")
        if n["body"]:
            parts.append("## Beschreibung\n\n" + n["body"])
        title = n["title"]
        if self.db.find_article_by_title(title):
            title += f" ({n['created'][:10]})"
        aid = self.db.save_article(title, "\n\n".join(parts), None, "Praxis, Baustelle", source="Notiz")
        for att in self.db.attachments(note_id=self.current):
            new = self.db.add_attachment(self.db.attachment_path(att), article_id=aid)
            if Path(new["filename"]).suffix.lower() in IMAGE_EXT:
                a = self.db.article(aid)
                self.db.save_article(a["title"], a["body"] + f"\n\n![{new['filename']}]({new['stored_name']})",
                                     None, a["tags"], aid, keep_version=False)
        self.ctx.notify("article")
        info(self, "Übernommen", f"Als Artikel „{title}“ gespeichert. 📚")
        self.ctx.navigate.emit("article", aid)

    def _delete(self) -> None:
        if self.current and confirm(self, "Löschen", "Diese Notiz wirklich löschen?"):
            self.db.delete_note(self.current)
            self.ctx.notify("note")
            self.new()

    def show_note(self, nid: int) -> None:
        self.filter.clear()
        self.refresh()
        self.load(nid)
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == nid:
                self.list.blockSignals(True)
                self.list.setCurrentRow(i)
                self.list.blockSignals(False)
