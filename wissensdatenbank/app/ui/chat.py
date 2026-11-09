"""Chat-Assistent: Panel im Hauptfenster oder als Leiste am rechten Bildschirmrand."""
from __future__ import annotations

import html
import re

from PySide6.QtCore import QObject, QPoint, QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent, QTextDocument
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QTextBrowser, QToolButton,
    QVBoxLayout, QWidget,
)

from ..config import APP_NAME, ACCENT
from ..core import assistant as core
from ..core import local_config
from ..core.db import Database
from .widgets import AppContext, FlowLayout

SUGGESTIONS = [
    "Druck R290 bei 0 °C",
    "R448A bei 3,5 bar und 8 °C Saugleitung",
    "Was ist Glide?",
    "Prüfpflicht 12 kg R404A",
    "Verdampfer vereist",
    "Wie evakuiere ich richtig?",
]

EDGE_WIDTH = 430
COLLAPSED_WIDTH = 54


def markdown_to_html(md: str) -> str:
    doc = QTextDocument()
    doc.setMarkdown(md)
    full = doc.toHtml()
    m = re.search(r"<body[^>]*>(.*)</body>", full, flags=re.S)
    return m.group(1) if m else html.escape(md)


class _Worker(QObject):
    done = Signal(object)

    def __init__(self, fn, question: str):
        super().__init__()
        self.fn = fn
        self.question = question

    def run(self) -> None:
        try:
            result = self.fn(self.question)
        except Exception as exc:  # Fehler als Antwort zurückgeben, nie den Thread sterben lassen
            result = exc
        self.done.emit(result)


class ChatInput(QPlainTextEdit):
    send = Signal()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.send.emit()
            return
        super().keyPressEvent(e)


class ChatPanel(QFrame):
    """Der eigentliche Chat. Wird im Hauptfenster oder in der Randleiste angezeigt."""
    detach_requested = Signal()
    close_requested = Signal()

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("ChatPanel")
        self.messages: list[tuple[str, str, list[core.Link]]] = []   # (rolle, markdown, links)
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._claude: core.ClaudeAssistant | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("💬 Assistent")
        title.setObjectName("SectionTitle")
        head.addWidget(title)
        self.mode = QLabel()
        self.mode.setObjectName("Muted")
        head.addWidget(self.mode)
        head.addStretch(1)
        self.btn_new = QToolButton()
        self.btn_new.setText("🧹")
        self.btn_new.setToolTip("Neuer Chat")
        self.btn_new.clicked.connect(self.clear)
        self.btn_detach = QToolButton()
        self.btn_detach.setText("📌")
        self.btn_detach.setToolTip("Am Bildschirmrand anheften / zurück ins Fenster")
        self.btn_detach.clicked.connect(self.detach_requested.emit)
        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setToolTip("Schließen")
        self.btn_close.clicked.connect(self.close_requested.emit)
        for b in (self.btn_new, self.btn_detach, self.btn_close):
            head.addWidget(b)
        lay.addLayout(head)

        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._on_link)
        lay.addWidget(self.view, 1)

        self.chips_w = QWidget()
        self.chips = FlowLayout(self.chips_w, spacing=6)
        for s in SUGGESTIONS:
            b = QPushButton(s)
            b.setObjectName("Chip")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, t=s: self.ask(t))
            self.chips.addWidget(b)
        lay.addWidget(self.chips_w)

        row = QHBoxLayout()
        self.input = ChatInput()
        self.input.setPlaceholderText("Frag mich was … (Enter = senden, Umschalt+Enter = neue Zeile)")
        self.input.setFixedHeight(70)
        self.input.send.connect(self._send)
        self.btn_send = QPushButton("➤")
        self.btn_send.setObjectName("Primary")
        self.btn_send.setFixedSize(48, 70)
        self.btn_send.setToolTip("Senden")
        self.btn_send.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(self.btn_send)
        lay.addLayout(row)

        ctx.changed.connect(self._on_changed)
        self.update_mode()
        self._render()

    # ------------------------------------------------------------- Modus
    def ai_enabled(self) -> bool:
        return local_config.get("assistant_mode", "offline") == "ki"

    def update_mode(self) -> None:
        if self.ai_enabled():
            self.mode.setText("· KI-Modus (Claude)")
            self._claude = None  # beim nächsten Mal mit aktuellem Schlüssel neu anlegen
        else:
            self.mode.setText("· offline")

    def _on_changed(self, kind: str) -> None:
        if kind in ("settings", "all"):
            self.update_mode()
            self._render()

    def _get_claude(self) -> core.ClaudeAssistant:
        if self._claude is None:
            key = local_config.get("anthropic_api_key") or None
            self._claude = core.ClaudeAssistant(self.ctx.db, key, app_name=APP_NAME)
        return self._claude

    # ------------------------------------------------------------- Ablauf
    def focus_input(self) -> None:
        self.input.setFocus()

    def clear(self) -> None:
        self.messages = []
        if self._claude:
            self._claude.reset()
        self.chips_w.setVisible(True)
        self._render()

    def ask(self, text: str) -> None:
        self.input.setPlainText(text)
        self._send()

    def _send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or self._thread is not None:
            return
        self.input.clear()
        self.chips_w.setVisible(False)
        self.messages.append(("user", text, []))
        self._render(typing=True)
        use_ai = self.ai_enabled()
        claude = self._get_claude() if use_ai else None
        db_path, att_dir = self.ctx.db.path, self.ctx.db.attachments_dir

        def work(q: str):
            # SQLite-Verbindungen sind an ihren Thread gebunden → eigene Verbindung für den Hintergrund
            db = Database(db_path, att_dir)
            try:
                offline = core.OfflineAssistant(db)
                if claude is not None:
                    try:
                        return claude.answer(q, db=db)
                    except Exception as exc:  # Rückfall auf offline mit Hinweis
                        ans = offline.answer(q)
                        ans.note = f"KI nicht verfügbar ({core.friendly_api_error(exc)}) – Offline-Antwort:"
                        return ans
                return offline.answer(q)
            finally:
                db.close()

        self._thread = QThread(self)
        self._worker = _Worker(work, text)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_answer)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self.btn_send.setEnabled(False)
        self._thread.start()

    def _cleanup_thread(self) -> None:
        if self._worker:
            self._worker.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self.btn_send.setEnabled(True)

    def _on_answer(self, result) -> None:
        if isinstance(result, Exception):
            self.messages.append(("assistant", f"Hoppla, da ist was schiefgelaufen: {result}", []))
        else:
            md = (f"*{result.note}*\n\n" if result.note else "") + result.text
            self.messages.append(("assistant", md, result.links))
        self._render()
        self.focus_input()

    # ------------------------------------------------------------- Anzeige
    def _render(self, typing: bool = False) -> None:
        dark = self.ctx.dark
        user_bg = ACCENT
        bot_bg = "#1E2A38" if dark else "#EEF3F9"
        bot_fg = "#E6EEF6" if dark else "#16212E"
        muted = "#93A3B5" if dark else "#5E6B7A"
        parts = [f"<div style='color:{muted}; margin-bottom:8px'>"]
        if not self.messages:
            parts.append(
                f"<p style='font-size:15pt; color:{bot_fg}'><b>Servus! 👋</b></p>"
                f"<p style='color:{bot_fg}'>Ich durchsuche dein {html.escape(APP_NAME)} und rechne Drücke, "
                "Temperaturen und CO₂-Äquivalente für dich. Frag einfach – zum Beispiel:</p>")
            if self.ai_enabled():
                parts.append("<p><i>KI-Modus aktiv: Antworten formuliert Claude auf Basis deines Wissens "
                             "(Internet nötig).</i></p>")
        parts.append("</div>")
        for role, md, links in self.messages:
            if role == "user":
                parts.append(
                    "<table width='100%' cellspacing='0' cellpadding='0' style='margin:6px 0'><tr>"
                    "<td width='18%'></td>"
                    f"<td style='background:{user_bg}; color:white; padding:8px 12px; border-radius:12px'>"
                    f"{html.escape(md).replace(chr(10), '<br>')}</td></tr></table>")
            else:
                link_html = ""
                if links:
                    items = " · ".join(f"<a href='{l.url}'>{_icon(l.kind)} {html.escape(l.title)}</a>"
                                       for l in links[:6])
                    link_html = f"<p style='margin-top:6px'><small>Öffnen: {items}</small></p>"
                parts.append(
                    "<table width='100%' cellspacing='0' cellpadding='0' style='margin:6px 0'><tr>"
                    f"<td style='background:{bot_bg}; color:{bot_fg}; padding:8px 12px; border-radius:12px'>"
                    f"{markdown_to_html(md)}{link_html}</td><td width='6%'></td></tr></table>")
        if typing:
            parts.append(f"<p style='color:{muted}'><i>… ich schau nach</i> 🔎</p>")
        self.view.setHtml("".join(parts))
        QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum()))

    def _on_link(self, url: QUrl) -> None:
        s = url.toString()
        m = re.match(r"kw:(\w+):(\d+)", s)
        if m:
            self.ctx.navigate.emit(m.group(1), int(m.group(2)))
            self.ctx.open_page.emit("__raise__")
        elif url.scheme() in ("http", "https"):
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)


def _icon(kind: str) -> str:
    return {"article": "📄", "refrigerant": "🧊", "fault": "🩺", "glossary": "📖", "note": "📝"}.get(kind, "•")


class EdgeWindow(QWidget):
    """Schmale Leiste am rechten Bildschirmrand, immer im Vordergrund. Einklappbar."""
    dock_requested = Signal()

    def __init__(self, ctx: AppContext, panel: ChatPanel):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.ctx = ctx
        self.setWindowTitle(f"{APP_NAME} – Assistent")
        self.setObjectName("Page")
        self.collapsed = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Griff zum Ein-/Ausklappen
        self.handle = QPushButton("⮞")
        self.handle.setToolTip("Einklappen / Ausklappen")
        self.handle.setFixedWidth(22)
        self.handle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.handle.setStyleSheet("border-radius: 0; padding: 0;")
        self.handle.clicked.connect(self.toggle_collapse)
        lay.addWidget(self.handle)

        self.collapsed_btn = QPushButton("💬")
        self.collapsed_btn.setToolTip("Assistent öffnen")
        self.collapsed_btn.setFixedWidth(COLLAPSED_WIDTH - 22)
        self.collapsed_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.collapsed_btn.setStyleSheet("font-size: 18pt; border-radius: 0;")
        self.collapsed_btn.clicked.connect(self.toggle_collapse)
        self.collapsed_btn.hide()
        lay.addWidget(self.collapsed_btn)

        self.panel = panel
        lay.addWidget(panel, 1)
        self.place()

    def place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if self.screen() is not None:
            screen = self.screen()
        geo = screen.availableGeometry()
        width = COLLAPSED_WIDTH if self.collapsed else EDGE_WIDTH
        self.setGeometry(geo.right() - width + 1, geo.top(), width, geo.height())

    def toggle_collapse(self) -> None:
        self.collapsed = not self.collapsed
        self.panel.setVisible(not self.collapsed)
        self.collapsed_btn.setVisible(self.collapsed)
        self.handle.setText("⮜" if self.collapsed else "⮞")
        self.place()
        if not self.collapsed:
            self.activateWindow()
            self.panel.focus_input()

    def take_panel(self) -> ChatPanel:
        self.panel.setParent(None)
        return self.panel
