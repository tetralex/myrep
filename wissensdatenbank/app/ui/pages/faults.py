"""Fehlersuche-Assistent: Symptom → Ursachen → Prüfschritte → Abhilfe."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..widgets import AppContext, Card, Page, clear_layout, confirm, hbox, muted, warn

LIKELIHOOD = {3: ("häufig", "#EF4444"), 2: ("gelegentlich", "#F5A524"), 1: ("selten", "#22C55E")}


class FaultEditor(QDialog):
    def __init__(self, ctx: AppContext, fid: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.fid = fid
        self.setWindowTitle("Fehlerbild bearbeiten" if fid else "Neues Fehlerbild")
        self.resize(1000, 640)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.symptom = QLineEdit()
        self.area = QComboBox()
        self.area.setEditable(True)
        self.area.addItems(sorted({f["area"] for f in ctx.db.faults() if f["area"]}))
        self.desc = QTextEdit()
        self.desc.setMaximumHeight(70)
        form.addRow("Symptom", self.symptom)
        form.addRow("Bereich", self.area)
        form.addRow("Beschreibung", self.desc)
        lay.addLayout(form)
        lay.addWidget(QLabel("Mögliche Ursachen (Wahrscheinlichkeit: 3 = häufig, 2 = gelegentlich, 1 = selten)"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Ursache", "Wahrsch. (1–3)", "Prüfschritte", "Abhilfe"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        lay.addWidget(self.table, 1)
        add = QPushButton("＋ Ursache")
        rem = QPushButton("－ Entfernen")
        add.clicked.connect(lambda: self._add_row({}))
        rem.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        lay.addLayout(hbox(add, rem, None))
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Speichern")
        bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if fid:
            f = ctx.db.fault(fid)
            self.symptom.setText(f["symptom"])
            self.area.setCurrentText(f["area"])
            self.desc.setPlainText(f["description"])
            for c in ctx.db.fault_causes(fid):
                self._add_row(dict(c))
        else:
            self._add_row({})

    def _add_row(self, c: dict) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col, key in enumerate(("cause", "likelihood", "checks", "remedy")):
            self.table.setItem(r, col, QTableWidgetItem(str(c.get(key, 2 if key == "likelihood" else ""))))

    def _save(self) -> None:
        if not self.symptom.text().strip():
            warn(self, "Symptom fehlt", "Bitte ein Symptom eingeben.")
            return
        causes = []
        for r in range(self.table.rowCount()):
            get = lambda c: (self.table.item(r, c).text() if self.table.item(r, c) else "").strip()
            try:
                lk = max(1, min(3, int(get(1) or 2)))
            except ValueError:
                lk = 2
            causes.append(dict(cause=get(0), likelihood=lk, checks=get(2), remedy=get(3)))
        self.ctx.db.save_fault(self.symptom.text(), self.area.currentText(), self.desc.toPlainText(), causes, self.fid)
        self.ctx.notify("fault")
        self.accept()


class FaultsPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, "🩺 Fehlersuche-Assistent",
                         "Symptom auswählen – wir gehen die möglichen Ursachen gemeinsam durch.")
        self.current: int | None = None
        split = QSplitter(Qt.Horizontal)
        self.root.addWidget(split, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("🔍 Symptom suchen …")
        self.filter.textChanged.connect(self.refresh)
        self.area = QComboBox()
        self.area.currentIndexChanged.connect(self._fill)
        ll.addWidget(self.filter)
        ll.addWidget(self.area)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda it, _p: self.show_fault(it.data(Qt.UserRole)) if it else None)
        ll.addWidget(self.list, 1)
        add = QPushButton("＋ Fehlerbild")
        add.clicked.connect(lambda: self._edit(None))
        ll.addWidget(add)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.title = QLabel("Welches Symptom hast du? 👈")
        self.title.setObjectName("Big")
        self.title.setWordWrap(True)
        self.desc = muted("")
        self.btn_edit = QPushButton("✏️ Bearbeiten / eigene Erfahrung ergänzen")
        self.btn_del = QPushButton("🗑")
        self.btn_del.setObjectName("Danger")
        self.btn_edit.clicked.connect(lambda: self._edit(self.current))
        self.btn_del.clicked.connect(self._delete)
        rl.addWidget(self.title)
        rl.addWidget(self.desc)
        rl.addLayout(hbox(self.btn_edit, self.btn_del, None))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.steps_w = QWidget()
        self.steps = QVBoxLayout(self.steps_w)
        self.steps.setSpacing(10)
        scroll.setWidget(self.steps_w)
        rl.addWidget(scroll, 1)
        split.addWidget(right)
        split.setSizes([320, 900])
        self.btn_edit.setEnabled(False)
        self.btn_del.setEnabled(False)
        ctx.changed.connect(lambda k: self.refresh() if k in ("fault", "all") else None)
        self.refresh()

    def refresh(self) -> None:
        cur = self.area.currentData()
        self.area.blockSignals(True)
        self.area.clear()
        self.area.addItem("Alle Bereiche", None)
        for a in sorted({f["area"] for f in self.db.faults() if f["area"]}):
            self.area.addItem(a, a)
        idx = self.area.findData(cur)
        self.area.setCurrentIndex(max(idx, 0))
        self.area.blockSignals(False)
        self._fill()
        if self.current and self.db.fault(self.current):
            self.show_fault(self.current)

    def _fill(self) -> None:
        flt = self.filter.text().strip().lower()
        area = self.area.currentData()
        self.list.blockSignals(True)
        self.list.clear()
        for f in self.db.faults():
            if area and f["area"] != area:
                continue
            if flt and flt not in f["symptom"].lower() and flt not in f["description"].lower():
                continue
            it = QListWidgetItem(f"⚠️ {f['symptom']}")
            it.setData(Qt.UserRole, f["id"])
            it.setToolTip(f["area"])
            self.list.addItem(it)
            if f["id"] == self.current:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)

    def show_fault(self, fid: int) -> None:
        f = self.db.fault(fid)
        if not f:
            return
        self.current = fid
        self.btn_edit.setEnabled(True)
        self.btn_del.setEnabled(True)
        self.title.setText(f["symptom"])
        self.desc.setText(f"{f['area']} · {f['description']}")
        clear_layout(self.steps)
        causes = self.db.fault_causes(fid)
        if not causes:
            self.steps.addWidget(muted("Noch keine Ursachen hinterlegt – ergänze deine Erfahrung! ✏️"))
        for i, c in enumerate(causes, start=1):
            label, color = LIKELIHOOD.get(c["likelihood"], ("?", "#888"))
            card = Card()
            head = QLabel(f"<b>{i}. {c['cause']}</b>  <span style='color:{color}'>● {label}</span>")
            head.setTextFormat(Qt.RichText)
            head.setWordWrap(True)
            card.lay.addWidget(head)
            if c["checks"]:
                l = QLabel(f"🔎 <b>Prüfen:</b> {c['checks']}")
                l.setWordWrap(True)
                card.lay.addWidget(l)
            if c["remedy"]:
                l = QLabel(f"🛠 <b>Abhilfe:</b> {c['remedy']}")
                l.setWordWrap(True)
                card.lay.addWidget(l)
            self.steps.addWidget(card)
        self.steps.addWidget(muted("Tipp: Ursachen sind nach Häufigkeit sortiert. Immer erst messen, dann tauschen. 😉"))
        self.steps.addStretch(1)
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == fid:
                self.list.blockSignals(True)
                self.list.setCurrentRow(i)
                self.list.blockSignals(False)

    def _edit(self, fid: int | None) -> None:
        dlg = FaultEditor(self.ctx, fid, self)
        dlg.exec()

    def _delete(self) -> None:
        f = self.db.fault(self.current) if self.current else None
        if f and confirm(self, "Löschen", f"Fehlerbild „{f['symptom']}“ löschen?"):
            self.db.delete_fault(f["id"])
            self.current = None
            clear_layout(self.steps)
            self.title.setText("Welches Symptom hast du? 👈")
            self.desc.setText("")
            self.ctx.notify("fault")
