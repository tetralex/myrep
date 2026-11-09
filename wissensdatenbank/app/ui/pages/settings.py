"""Daten & Einstellungen."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QInputDialog, QLabel,
    QPushButton, QScrollArea, QSpinBox, QWidget,
)
from PySide6.QtCore import Qt

from ...config import APP_NAME, APP_VERSION
from ...core import package
from ..widgets import AppContext, Card, Page, confirm, hbox, info, muted, warn


class SettingsPage(Page):
    def __init__(self, ctx: AppContext, apply_settings):
        super().__init__(ctx, "⚙️ Daten & Einstellungen", "Aussehen, Sicherung, Export und Import.")
        self.apply_settings = apply_settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(16)
        grid.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(inner)
        self.root.addWidget(scroll, 1)

        look = Card("Aussehen", "🎨")
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItems(["Wie Windows", "Hell", "Dunkel"])
        self.font = QSpinBox()
        self.font.setRange(9, 18)
        self.font.setSuffix(" pt")
        self.start = QComboBox()
        self.start_keys = ["home", "articles", "tools", "refrigerants", "faults", "notes"]
        self.start.addItems(["Startseite", "Wissensartikel", "Werkzeugkasten", "Kältemittel", "Fehlersuche", "Notizen"])
        self.unit = QComboBox()
        self.unit.addItems(["bar(ü)", "bar(a)"])
        form.addRow("Theme", self.theme)
        form.addRow("Schriftgröße", self.font)
        form.addRow("Beim Start öffnen", self.start)
        form.addRow("Standard-Druckeinheit", self.unit)
        look.lay.addLayout(form)
        save = QPushButton("Übernehmen")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        look.lay.addLayout(hbox(save, None))
        look.lay.addStretch(1)
        grid.addWidget(look, 0, 0)

        exp = Card("Export", "📤")
        exp.lay.addWidget(muted("Komplette Datenbank als Wissenspaket (.zip) – zum Sichern oder Weitergeben an Kollegen."))
        b1 = QPushButton("📦 Alles exportieren …")
        b1.clicked.connect(self._export_all)
        self.with_notes = QCheckBox("Notizen mit exportieren (enthalten evtl. Kundendaten)")
        self.with_notes.setChecked(False)
        b2 = QPushButton("📚 Nur ausgewählte Kategorie …")
        b2.clicked.connect(self._export_category)
        exp.lay.addWidget(self.with_notes)
        exp.lay.addLayout(hbox(b1, b2, None))
        exp.lay.addStretch(1)
        grid.addWidget(exp, 0, 1)

        bak = Card("Sicherung", "🛟")
        self.auto_backup = QCheckBox("Beim Beenden automatisch sichern (letzte 10 bleiben)")
        bak.lay.addWidget(self.auto_backup)
        self.backup_info = muted("")
        bak.lay.addWidget(self.backup_info)
        b3 = QPushButton("💾 Jetzt sichern")
        b3.clicked.connect(self._backup_now)
        b4 = QPushButton("↩️ Sicherung wiederherstellen …")
        b4.clicked.connect(self._restore)
        b5 = QPushButton("📂 Datenordner öffnen")
        b5.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.db.path.parent))))
        bak.lay.addLayout(hbox(b3, b4, b5, None))
        bak.lay.addStretch(1)
        grid.addWidget(bak, 1, 0)

        about = Card("Über", "ℹ️")
        about.lay.addWidget(QLabel(f"<b>{APP_NAME}</b> Version {APP_VERSION}"))
        about.lay.addWidget(muted(f"Datenbank: {self.db.path}"))
        about.lay.addWidget(muted("Alle Inhalte ohne Gewähr – maßgeblich sind Herstellerangaben und die "
                                  "Originaltexte von Normen und Verordnungen."))
        b6 = QPushButton("🔁 Suchindex neu aufbauen")
        b6.clicked.connect(self._reindex)
        about.lay.addLayout(hbox(b6, None))
        about.lay.addStretch(1)
        grid.addWidget(about, 1, 1)
        grid.setRowStretch(2, 1)
        self.refresh()

    def refresh(self) -> None:
        s = self.db
        self.theme.setCurrentIndex(["system", "light", "dark"].index(s.get_setting("theme", "system")))
        self.font.setValue(int(s.get_setting("font_size", 11)))
        key = s.get_setting("start_page", "home")
        self.start.setCurrentIndex(self.start_keys.index(key) if key in self.start_keys else 0)
        self.unit.setCurrentIndex(0 if s.get_setting("gauge", True) else 1)
        self.auto_backup.setChecked(bool(s.get_setting("auto_backup", True)))
        backups = package.list_backups(self.db)
        self.backup_info.setText(f"{len(backups)} Sicherung(en) vorhanden" +
                                 (f", letzte: {backups[0].stem[7:].replace('_', ' ')}" if backups else ""))

    def _save(self) -> None:
        s = self.db
        s.set_setting("theme", ["system", "light", "dark"][self.theme.currentIndex()])
        s.set_setting("font_size", self.font.value())
        s.set_setting("start_page", self.start_keys[self.start.currentIndex()])
        s.set_setting("gauge", self.unit.currentIndex() == 0)
        s.set_setting("auto_backup", self.auto_backup.isChecked())
        state = s.get_setting("calc_state", {}) or {}
        for k in ("sh_gauge", "sc_gauge", "sat_gauge", "cy_gauge"):
            state[k] = self.unit.currentIndex() == 0
        s.set_setting("calc_state", state)
        self.apply_settings()
        info(self, "Gespeichert", "Einstellungen übernommen. ✅\n(Die Druckeinheit gilt ab dem nächsten Start.)")

    def _export_all(self) -> None:
        name = f"Wissenspaket_{datetime.now():%Y-%m-%d}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "Wissenspaket speichern", name, "Wissenspaket (*.zip)")
        if path:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                out = package.export_package(self.db, path, include_notes=self.with_notes.isChecked())
            finally:
                QApplication.restoreOverrideCursor()
            info(self, "Exportiert", f"Gespeichert unter:\n{out}")

    def _export_category(self) -> None:
        cats = {self.db.category_path(c["id"]): c["id"] for c in self.db.categories()}
        if not cats:
            warn(self, "Keine Kategorien", "Es gibt noch keine Kategorien.")
            return
        name, ok = QInputDialog.getItem(self, "Kategorie exportieren", "Kategorie:", sorted(cats), 0, False)
        if not ok:
            return
        ids = [a["id"] for a in self.db.articles(category_id=cats[name])]
        safe = "".join(ch for ch in name if ch.isalnum() or ch in " -_").strip()
        path, _ = QFileDialog.getSaveFileName(self, "Wissenspaket speichern", f"{safe}.zip", "Wissenspaket (*.zip)")
        if path:
            out = package.export_package(self.db, path, article_ids=ids)
            info(self, "Exportiert", f"{len(ids)} Artikel exportiert:\n{out}")

    def _backup_now(self) -> None:
        out = package.auto_backup(self.db)
        self.refresh()
        info(self, "Gesichert", f"Sicherung erstellt:\n{out.name}")

    def _restore(self) -> None:
        start = str(package.backup_dir(self.db))
        path, _ = QFileDialog.getOpenFileName(self, "Sicherung wiederherstellen", start, "Wissenspaket (*.zip)")
        if not path:
            return
        if not confirm(self, "Wiederherstellen",
                       "Die aktuelle Datenbank wird komplett durch die Sicherung ersetzt.\n"
                       "Vorher wird automatisch eine Sicherung des aktuellen Stands angelegt. Fortfahren?"):
            return
        package.auto_backup(self.db)
        result = package.import_package(self.db, path, replace=True)
        self.ctx.notify("all")
        self.refresh()
        if result.errors:
            warn(self, "Fehler", "\n".join(result.errors))
        else:
            info(self, "Wiederhergestellt", f"Sicherung eingespielt: {result.summary()}")

    def _reindex(self) -> None:
        self.db.rebuild_index()
        info(self, "Fertig", "Suchindex neu aufgebaut. 🔍")
