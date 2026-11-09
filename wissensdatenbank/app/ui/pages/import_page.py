"""Neues Wissen importieren: Dateien, Ordner, Text, Wissenspakete."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...core import importer, package
from ..widgets import AppContext, Card, Page, hbox, info, muted
from .articles import category_combo

FORMATS_HELP = (
    "<b>Unterstützt:</b> Markdown (.md), Text (.txt), HTML, PDF, Word (.docx), Bilder (.png, .jpg …), "
    "CSV und ganze Ordner (Unterordner werden zu Kategorien).<br>"
    "<b>CSV fürs Glossar:</b> Spalten <code>Begriff;Erklärung</code><br>"
    "<b>CSV für Kältemittel:</b> Spalten wie <code>code;name;safety;gwp_ar4;gwp_ar5;glide;nbp;…</code>"
)


class DropZone(QFrame):
    def __init__(self, on_drop):
        super().__init__()
        self.on_drop = on_drop
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(170)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        icon = QLabel("📥")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 40pt; background: transparent;")
        text = QLabel("Dateien oder Ordner hierher ziehen")
        text.setAlignment(Qt.AlignCenter)
        text.setObjectName("SectionTitle")
        text.setStyleSheet("background: transparent;")
        sub = muted("PDF, Word, Markdown, Text, HTML, Bilder, CSV – auch mehrere auf einmal")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("background: transparent;")
        lay.addWidget(icon)
        lay.addWidget(text)
        lay.addWidget(sub)

    def _set_active(self, on: bool) -> None:
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, _e):
        self._set_active(False)

    def dropEvent(self, e):
        self._set_active(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.on_drop(paths)


class ImportPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, "📥 Wissen importieren",
                         "Bring dein Wissen rein: Unterlagen, Datenblätter, Fotos, Mitschriften – oder Pakete von Kollegen.")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)
        scroll.setWidget(inner)
        self.root.addWidget(scroll, 1)

        # ---------------------------------------------------------- Dateien
        files_card = Card("Dateien & Ordner", "📂")
        self.drop = DropZone(self.import_paths)
        files_card.lay.addWidget(self.drop)
        pick_files = QPushButton("📄 Dateien auswählen …")
        pick_files.setObjectName("Primary")
        pick_folder = QPushButton("📁 Ordner auswählen …")
        pick_files.clicked.connect(self._pick_files)
        pick_folder.clicked.connect(self._pick_folder)
        files_card.lay.addLayout(hbox(pick_files, pick_folder, None))

        opts = QFormLayout()
        self.category = QComboBox()
        new_cat = QPushButton("＋")
        new_cat.setToolTip("Neue Kategorie")
        new_cat.setMaximumWidth(44)
        new_cat.clicked.connect(self._new_category)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("optional, z. B. Datenblatt, Hersteller X")
        self.dup_rename = QRadioButton("als neuen Artikel (2)")
        self.dup_skip = QRadioButton("überspringen")
        self.dup_replace = QRadioButton("aktualisieren")
        self.dup_rename.setChecked(True)
        self.attach = QCheckBox("Originaldatei als Anhang speichern (PDF/Word/HTML)")
        self.attach.setChecked(True)
        opts.addRow("Zielkategorie", hbox(self.category, new_cat))
        opts.addRow("Tags", self.tags)
        opts.addRow("Titel gibt's schon", hbox(self.dup_rename, self.dup_skip, self.dup_replace, None))
        opts.addRow("", self.attach)
        files_card.lay.addLayout(opts)
        help_lbl = QLabel(FORMATS_HELP)
        help_lbl.setWordWrap(True)
        help_lbl.setObjectName("Muted")
        files_card.lay.addWidget(help_lbl)
        grid.addWidget(files_card, 0, 0, 2, 1)

        # ---------------------------------------------------------- Text
        text_card = Card("Text einfügen", "✍️")
        self.text_title = QLineEdit()
        self.text_title.setPlaceholderText("Titel (optional – sonst erste Zeile)")
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Text hier einfügen – z. B. aus einer E-Mail, Webseite oder Mitschrift.\n"
                                     "Markdown (# Überschrift, - Liste, | Tabelle |) wird unterstützt.")
        self.text.setMinimumHeight(160)
        paste = QPushButton("📋 Aus Zwischenablage")
        paste.clicked.connect(lambda: self.text.setPlainText(QGuiApplication.clipboard().text()))
        save_text = QPushButton("💾 Als Artikel speichern")
        save_text.setObjectName("Primary")
        save_text.clicked.connect(self._save_text)
        text_card.lay.addWidget(self.text_title)
        text_card.lay.addWidget(self.text, 1)
        text_card.lay.addLayout(hbox(paste, None, save_text))
        grid.addWidget(text_card, 0, 1)

        # ---------------------------------------------------------- Pakete
        pkg_card = Card("Wissenspaket (.zip)", "📦")
        pkg_card.lay.addWidget(muted(
            "Ein Wissenspaket enthält Artikel, Anhänge, Glossar, Kältemittel und Fehlerbilder. "
            "Kollegen erstellen es unter „Daten & Einstellungen → Exportieren“. "
            "Beim Einspielen bleibt dein eigenes Wissen erhalten."))
        pkg_btn = QPushButton("📦 Paket einspielen …")
        pkg_btn.clicked.connect(self._import_package)
        pkg_card.lay.addLayout(hbox(pkg_btn, None))
        grid.addWidget(pkg_card, 1, 1)

        # ---------------------------------------------------------- Ergebnis
        res_card = Card("Ergebnis", "✅")
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.summary = QLabel("Noch nichts importiert.")
        self.summary.setObjectName("SectionTitle")
        self.log = QListWidget()
        self.log.setMinimumHeight(160)
        self.log.itemDoubleClicked.connect(self._open_logged)
        res_card.lay.addWidget(self.progress)
        res_card.lay.addWidget(self.summary)
        res_card.lay.addWidget(self.log)
        res_card.lay.addWidget(muted("Doppelklick öffnet den importierten Artikel."))
        grid.addWidget(res_card, 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        ctx.changed.connect(lambda k: self._fill_categories() if k in ("category", "article", "all") else None)
        self._fill_categories()

    # ---------------------------------------------------------- Hilfen
    def _fill_categories(self) -> None:
        cur = self.category.currentData()
        category_combo(self.db, self.category, cur)

    def _new_category(self) -> None:
        name, ok = QInputDialog.getText(self, "Neue Kategorie", "Name (Unterkategorie mit „/“, z. B. Hersteller/Bitzer):")
        if ok and name.strip():
            cid = self.db.find_or_create_category(name.split("/"))
            self.ctx.notify("category")
            category_combo(self.db, self.category, cid)

    def _duplicates(self) -> str:
        if self.dup_skip.isChecked():
            return importer.DUP_SKIP
        if self.dup_replace.isChecked():
            return importer.DUP_REPLACE
        return importer.DUP_RENAME

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Dateien importieren", "", importer.FILE_FILTER)
        if paths:
            self.import_paths(paths)

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Ordner importieren")
        if folder:
            self.import_paths([folder])

    # ---------------------------------------------------------- Import
    def import_paths(self, paths: list[str]) -> None:
        self.progress.setVisible(True)
        self.progress.setValue(0)

        def progress(i, total, name):
            self.progress.setMaximum(total)
            self.progress.setValue(i)
            self.summary.setText(f"Importiere {name} … ({i}/{total})")
            QApplication.processEvents()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = importer.import_paths(self.db, [Path(p) for p in paths], self.category.currentData(),
                                           self.tags.text(), self.attach.isChecked(), self._duplicates(), progress)
        finally:
            QApplication.restoreOverrideCursor()
        self.progress.setVisible(False)
        self._show_result(result)

    def _save_text(self) -> None:
        result = importer.import_text(self.db, self.text.toPlainText(), self.text_title.text(),
                                      self.category.currentData(), self.tags.text(), self._duplicates())
        if result.created or result.updated:
            self.text.clear()
            self.text_title.clear()
        self._show_result(result)

    def _import_package(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Wissenspaket einspielen", "", "Wissenspaket (*.zip)")
        if not path:
            return
        dup = self._duplicates()
        if dup == importer.DUP_RENAME:
            dup = importer.DUP_SKIP  # bei Paketen: Doppelte standardmäßig überspringen
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = package.import_package(self.db, path, replace=False, duplicates=dup)
        finally:
            QApplication.restoreOverrideCursor()
        self._show_result(result)

    def _show_result(self, result: importer.ImportResult) -> None:
        self.summary.setText(f"Fertig: {result.summary()} 🎉" if not result.errors else f"Fertig: {result.summary()}")
        self.log.clear()
        for t in result.created:
            self._log("🆕", t)
        for t in result.updated:
            self._log("🔄", t)
        for t in result.skipped:
            self._log("⏭", t)
        for t in result.errors:
            it = QListWidgetItem("❌ " + t)
            it.setForeground(Qt.red)
            self.log.addItem(it)
        self.ctx.notify("all")
        if len(result.article_ids) == 1 and not result.errors:
            info(self, "Importiert", "Artikel importiert – ich öffne ihn für dich. 📚")
            self.ctx.navigate.emit("article", result.article_ids[0])

    def _log(self, icon: str, title: str) -> None:
        it = QListWidgetItem(f"{icon} {title}")
        a = self.db.find_article_by_title(title)
        if a:
            it.setData(Qt.UserRole, a["id"])
        self.log.addItem(it)

    def _open_logged(self, it) -> None:
        aid = it.data(Qt.UserRole)
        if aid:
            self.ctx.navigate.emit("article", int(aid))
