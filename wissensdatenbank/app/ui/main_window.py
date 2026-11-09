"""Hauptfenster mit Navigation."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..config import APP_NAME, APP_VERSION, resource_path
from ..core import package
from . import theme
from .pages.articles import ArticlesPage
from .pages.faults import FaultsPage
from .pages.glossary import GlossaryPage
from .pages.home import HomePage
from .pages.import_page import ImportPage
from .pages.notes import NotesPage
from .pages.refrigerants import RefrigerantsPage
from .pages.search import QuickSearch, SearchPage
from .pages.settings import SettingsPage
from .pages.tools import ToolsPage
from .chat import ChatPanel, EdgeWindow
from .widgets import AppContext

NAV = [
    ("home", "🏠  Start"),
    ("articles", "📚  Wissensartikel"),
    ("refrigerants", "🧊  Kältemittel"),
    ("tools", "🧮  Werkzeugkasten"),
    ("faults", "🩺  Fehlersuche"),
    ("glossary", "📖  Glossar"),
    ("notes", "📝  Notizen"),
    ("import", "📥  Wissen importieren"),
    ("settings", "⚙️  Daten & Einstellungen"),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        icon = resource_path("assets/icon.png")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1360, 860)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setCentralWidget(central)

        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(250)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 18, 12, 14)
        title = QLabel(f"❄️ {APP_NAME}")
        title.setObjectName("AppTitle")
        sub = QLabel("Wissen für Kältetechniker")
        sub.setObjectName("AppSub")
        sl.addWidget(title)
        sl.addWidget(sub)
        search_btn = QPushButton("🔍  Suchen …      Strg+K")
        search_btn.setStyleSheet("text-align: left;")
        search_btn.clicked.connect(self.quick_search)
        sl.addWidget(search_btn)
        sl.addSpacing(8)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        for key, label in NAV:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, key)
            self.nav.addItem(it)
        self.nav.currentRowChanged.connect(self._on_nav)
        sl.addWidget(self.nav, 1)
        self.chat_btn = QPushButton("💬  Assistent      Strg+J")
        self.chat_btn.setObjectName("Primary")
        self.chat_btn.setStyleSheet("text-align: left;")
        self.chat_btn.clicked.connect(self.toggle_chat)
        sl.addWidget(self.chat_btn)
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(self._toggle_theme)
        sl.addWidget(self.theme_btn)
        ver = QLabel(f"v{APP_VERSION}")
        ver.setObjectName("AppSub")
        sl.addWidget(ver)
        lay.addWidget(side)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.pages = {
            "home": HomePage(ctx),
            "articles": ArticlesPage(ctx),
            "refrigerants": RefrigerantsPage(ctx),
            "tools": ToolsPage(ctx),
            "faults": FaultsPage(ctx),
            "glossary": GlossaryPage(ctx),
            "notes": NotesPage(ctx),
            "import": ImportPage(ctx),
            "settings": SettingsPage(ctx, self.apply_settings),
            "search": SearchPage(ctx),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)

        # Chat-Assistent: rechts im Fenster oder als Leiste am Bildschirmrand
        self.central_layout = lay
        self.chat = ChatPanel(ctx)
        self.chat.setFixedWidth(420)
        self.chat.setStyleSheet("QFrame#ChatPanel { border-left: 1px solid rgba(127,127,127,0.25); }")
        self.chat.hide()
        lay.addWidget(self.chat)
        self.chat.detach_requested.connect(self.toggle_edge)
        self.chat.close_requested.connect(self.close_chat)
        self.edge: EdgeWindow | None = None

        ctx.navigate.connect(self.open_item)
        ctx.open_page.connect(self.open_page)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.quick_search)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.quick_search)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: (self.open_page("articles"),
                                                                    self.pages["articles"]._new_article()))
        QShortcut(QKeySequence("Ctrl+I"), self, activated=lambda: self.open_page("import"))
        QShortcut(QKeySequence("Ctrl+J"), self, activated=self.toggle_chat)
        QShortcut(QKeySequence("F5"), self, activated=lambda: self.ctx.notify("all"))
        self._update_theme_button()
        self.open_page(ctx.db.get_setting("start_page", "home"))

    # ---------------------------------------------------------- Navigation
    def _on_nav(self, row: int) -> None:
        if 0 <= row < len(NAV):
            key = NAV[row][0]
            page = self.pages[key]
            self.stack.setCurrentWidget(page)
            if key in ("home", "settings"):
                page.refresh()

    def _select_nav(self, key: str) -> None:
        keys = [k for k, _ in NAV]
        self.nav.blockSignals(True)
        if key in keys:
            self.nav.setCurrentRow(keys.index(key))
        else:
            self.nav.clearSelection()
        self.nav.blockSignals(False)

    def open_page(self, key: str) -> None:
        if key == "__raise__":
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()
            return
        if key.startswith("search:"):
            self.stack.setCurrentWidget(self.pages["search"])
            self._select_nav("search")
            self.pages["search"].search(key[7:])
            return
        if key not in self.pages:
            key = "home"
        self.stack.setCurrentWidget(self.pages[key])
        self._select_nav(key)
        if key in ("home", "settings"):
            self.pages[key].refresh()

    def open_item(self, kind: str, ref_id: int) -> None:
        if kind == "article":
            self.open_page("articles")
            self.pages["articles"].show_article(ref_id)
        elif kind == "refrigerant":
            self.open_page("refrigerants")
            self.pages["refrigerants"].filter.clear()
            self.pages["refrigerants"].select(ref_id)
        elif kind == "glossary":
            self.open_page("glossary")
            g = self.pages["glossary"]
            g.filter.clear()
            g._set_letter(None)
            g.show_entry(ref_id)
        elif kind == "fault":
            self.open_page("faults")
            f = self.pages["faults"]
            f.filter.clear()
            f.show_fault(ref_id)
        elif kind == "note":
            self.open_page("notes")
            self.pages["notes"].show_note(ref_id)

    def quick_search(self) -> None:
        dlg = QuickSearch(self.ctx, self)
        geo = self.geometry()
        dlg.move(geo.x() + (geo.width() - dlg.width()) // 2, geo.y() + 90)
        dlg.input.setFocus()
        dlg.exec()

    # ---------------------------------------------------------- Assistent
    def toggle_chat(self) -> None:
        if self.edge is not None:
            if self.edge.collapsed:
                self.edge.toggle_collapse()
            else:
                self.edge.activateWindow()
                self.chat.focus_input()
            return
        self.chat.setVisible(not self.chat.isVisible())
        if self.chat.isVisible():
            self.chat.focus_input()

    def toggle_edge(self) -> None:
        """Assistent an den rechten Bildschirmrand heften bzw. zurück ins Fenster holen."""
        if self.edge is None:
            self.central_layout.removeWidget(self.chat)
            self.chat.setMinimumWidth(0)
            self.chat.setMaximumWidth(16777215)
            self.edge = EdgeWindow(self.ctx, self.chat)
            self.chat.show()
            self.edge.show()
            self.chat.focus_input()
        else:
            panel = self.edge.take_panel()
            self.edge.close()
            self.edge.deleteLater()
            self.edge = None
            panel.setFixedWidth(420)
            self.central_layout.addWidget(panel)
            panel.show()

    def open_edge(self) -> None:
        if self.edge is None:
            self.toggle_edge()

    def close_chat(self) -> None:
        if self.edge is not None:
            self.toggle_edge()
        self.chat.hide()

    # ---------------------------------------------------------- Theme
    def apply_settings(self) -> None:
        app = QApplication.instance()
        mode = self.ctx.db.get_setting("theme", "system")
        dark = theme.system_prefers_dark() if mode == "system" else mode == "dark"
        self.ctx.dark = dark
        theme.apply_palette(app, dark)
        app.setStyleSheet(theme.stylesheet(dark, int(self.ctx.db.get_setting("font_size", 11))))
        self._update_theme_button()
        self.ctx.notify("all")

    def _toggle_theme(self) -> None:
        self.ctx.db.set_setting("theme", "light" if self.ctx.dark else "dark")
        self.apply_settings()

    def _update_theme_button(self) -> None:
        self.theme_btn.setText("☀️  Hell" if self.ctx.dark else "🌙  Dunkel")

    # ---------------------------------------------------------- Drag & Drop überall
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.open_page("import")
            self.pages["import"].import_paths(paths)

    # ---------------------------------------------------------- Beenden
    def closeEvent(self, e):
        if self.edge is not None:
            self.edge.close()
        if self.ctx.db.get_setting("auto_backup", True):
            try:
                package.auto_backup(self.ctx.db)
            except Exception:
                pass
        super().closeEvent(e)
