"""Startseite / Dashboard."""
from __future__ import annotations

import random
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QStringListModel
from PySide6.QtWidgets import (
    QCompleter, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

from ...config import APP_NAME
from ..widgets import AppContext, Card, LinkButton, Page, clear_layout, muted


def greeting() -> str:
    h = datetime.now().hour
    if h < 11:
        return "Guten Morgen! ☕"
    if h < 17:
        return "Servus! 👋"
    return "Guten Abend! 🌙"


class HomePage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)
        scroll.setWidget(inner)
        self.root.addWidget(scroll)

        hello = QLabel(greeting())
        hello.setObjectName("Hero")
        lay.addWidget(hello)
        lay.addWidget(muted(f"Willkommen bei {APP_NAME} – deinem Kältetechnik-Wissen an einem Ort."))

        self.search = QLineEdit()
        self.search.setObjectName("SearchBig")
        self.search.setPlaceholderText("🔍  Was suchst du heute?  (z. B. Überhitzung, R290, Schauglas …)")
        self.search.returnPressed.connect(self._do_search)
        self.completer_model = QStringListModel()
        completer = QCompleter(self.completer_model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.activated.connect(lambda _t: self._do_search())
        self.search.setCompleter(completer)
        lay.addWidget(self.search)

        # Schnellzugriff-Kacheln
        tiles = QGridLayout()
        tiles.setSpacing(14)
        tile_defs = [
            ("📚", "Wissensartikel", "Grundlagen bis Normen", "articles"),
            ("🧊", "Kältemittel", "Daten, GWP, Druck-Temp.", "refrigerants"),
            ("🧮", "Werkzeugkasten", "Überhitzung, CO₂-Äq. …", "tools"),
            ("🩺", "Fehlersuche", "Symptom → Ursache", "faults"),
            ("📥", "Wissen importieren", "PDF, Word, Bilder, Ordner", "import"),
            ("📝", "Baustellen-Log", "Notizen & Messwerte", "notes"),
        ]
        for i, (icon, title, sub, key) in enumerate(tile_defs):
            card = Card(clickable=True)
            ic = QLabel(icon)
            ic.setStyleSheet("font-size: 26pt;")
            card.lay.addWidget(ic)
            t = QLabel(title)
            t.setObjectName("SectionTitle")
            card.lay.addWidget(t)
            card.lay.addWidget(muted(sub))
            card.clicked.connect(lambda k=key: self.ctx.open_page.emit(k))
            tiles.addWidget(card, i // 3, i % 3)
        lay.addLayout(tiles)

        row = QHBoxLayout()
        row.setSpacing(14)
        self.recent_card = Card("Zuletzt angesehen", "🕑")
        self.recent_box = QVBoxLayout()
        self.recent_card.lay.addLayout(self.recent_box)
        self.recent_card.lay.addStretch(1)
        self.fav_card = Card("Favoriten", "⭐")
        self.fav_box = QVBoxLayout()
        self.fav_card.lay.addLayout(self.fav_box)
        self.fav_card.lay.addStretch(1)
        row.addWidget(self.recent_card, 1)
        row.addWidget(self.fav_card, 1)
        lay.addLayout(row)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        from PySide6.QtWidgets import QFrame
        self.tip = QFrame()
        self.tip.setObjectName("AccentCard")
        tl = QVBoxLayout(self.tip)
        tl.setContentsMargins(20, 16, 20, 16)
        tt = QLabel("💡  Tipp des Tages")
        tt.setStyleSheet("font-weight: 700; font-size: 13pt;")
        tl.addWidget(tt)
        self.tip_text = QLabel()
        self.tip_text.setWordWrap(True)
        tl.addWidget(self.tip_text)
        bottom.addWidget(self.tip, 2)

        self.stats_card = Card("Deine Datenbank", "📊")
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        self.stats_card.lay.addWidget(self.stats_label)
        bottom.addWidget(self.stats_card, 1)
        lay.addLayout(bottom)
        lay.addStretch(1)

        ctx.changed.connect(lambda _k: self.refresh())
        QTimer.singleShot(0, self.refresh)

    def _do_search(self) -> None:
        text = self.search.text().strip()
        if text:
            self.ctx.open_page.emit("search:" + text)

    def _fill(self, box, rows, empty: str) -> None:
        clear_layout(box)
        if not rows:
            box.addWidget(muted(empty))
            return
        for r in rows[:8]:
            box.addWidget(LinkButton("📄  " + r["title"], lambda rid=r["id"]: self.ctx.navigate.emit("article", rid)))

    def refresh(self) -> None:
        self._fill(self.recent_box, self.db.recent_articles(), "Noch nichts angesehen – leg los! 🚀")
        self._fill(self.fav_box, self.db.favorite_articles(), "Noch keine Favoriten. Markier Artikel mit ⭐.")
        tips = self.db.get_setting("tips", []) or ["Strg+K öffnet überall die Schnellsuche."]
        rnd = random.Random(datetime.now().strftime("%Y-%m-%d"))
        self.tip_text.setText(rnd.choice(tips))
        s = self.db.stats()
        self.stats_label.setText(
            f"📚 {s['articles']} Artikel\n🧊 {s['refrigerants']} Kältemittel\n"
            f"🩺 {s['faults']} Fehlerbilder\n📖 {s['glossary']} Glossarbegriffe\n📝 {s['notes']} Notizen")
        titles = [a["title"] for a in self.db.articles()] + [g["term"] for g in self.db.glossary()] + \
                 [r["code"] for r in self.db.refrigerants()]
        self.completer_model.setStringList(sorted(set(titles), key=str.lower))
