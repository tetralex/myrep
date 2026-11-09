"""Kältemittel-Datenbank: Tabelle, Detail mit Druck-Temperatur-Tabelle/Diagramm, Vergleich."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from ...calc import properties
from ...calc.units import P_ATM_BAR
from ..widgets import AppContext, Page, confirm, hbox, muted, warn

SAFETY_COLORS = {"A1": "#22C55E", "A2L": "#F5A524", "A2": "#F97316", "A3": "#EF4444",
                 "B1": "#8B5CF6", "B2L": "#A855F7", "B2": "#9333EA", "B3": "#7E22CE"}


def fmt(v, digits: int = 1, unit: str = "") -> str:
    if v is None or v == "":
        return "–"
    if isinstance(v, float):
        s = f"{v:.{digits}f}".replace(".", ",")
        if digits and "," in s:
            s = s.rstrip("0").rstrip(",")
    else:
        s = str(v)
    return f"{s} {unit}".strip()


def nice_ticks(lo: float, hi: float, max_ticks: int = 8) -> list[float]:
    """Gut lesbare Achsenteilung (1-2-2,5-5-10er Schritte)."""
    span = hi - lo
    if span <= 0:
        return [lo]
    import math
    raw = span / max_ticks
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.ceil(lo / step) * step
    ticks = []
    v = start
    while v <= hi + 1e-9:
        ticks.append(round(v, 6))
        v += step
    return ticks


class PTChart(QWidget):
    """Einfaches Druck-Temperatur-Diagramm (ohne zusätzliche Bibliothek)."""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.series: list[tuple[str, QColor, list[tuple[float, float]]]] = []
        self.gauge = True
        self.setMinimumHeight(260)

    def set_data(self, series, gauge: bool) -> None:
        self.series = series
        self.gauge = gauge
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        text_col = QColor("#E6EEF6" if self.ctx.dark else "#16212E")
        grid_col = QColor(127, 127, 127, 60)
        m_l, m_r, m_t, m_b = 56, 16, 14, 34
        w, h = self.width() - m_l - m_r, self.height() - m_t - m_b
        pts = [pt for _, _, s in self.series for pt in s]
        if not pts or w < 50 or h < 50:
            p.setPen(text_col)
            p.drawText(self.rect(), Qt.AlignCenter, "Keine Stoffdaten verfügbar")
            return
        tmin, tmax = min(t for t, _ in pts), max(t for t, _ in pts)
        pmin, pmax = min(0.0, min(v for _, v in pts)), max(v for _, v in pts) * 1.05
        if tmax == tmin or pmax == pmin:
            return

        def X(t):
            return m_l + (t - tmin) / (tmax - tmin) * w

        def Y(v):
            return m_t + h - (v - pmin) / (pmax - pmin) * h

        for val in nice_ticks(pmin, pmax):
            y = Y(val)
            p.setPen(QPen(grid_col, 1))
            p.drawLine(m_l, int(y), m_l + w, int(y))
            p.setPen(text_col)
            p.drawText(4, int(y) + 4, f"{val:g}".replace(".", ","))
        for val in nice_ticks(tmin, tmax):
            x = X(val)
            p.setPen(QPen(grid_col, 1))
            p.drawLine(int(x), m_t, int(x), m_t + h)
            p.setPen(text_col)
            p.drawText(int(x) - 12, m_t + h + 18, f"{val:g}")
        p.setPen(text_col)
        p.drawText(m_l + w - 110, self.height() - 2, "Temperatur in °C")
        p.drawText(m_l + 6, m_t + 12, "bar(ü)" if self.gauge else "bar(a)")

        legend_y = m_t + 14
        for name, color, s in self.series:
            if len(s) < 2:
                continue
            path = QPainterPath(QPointF(X(s[0][0]), Y(s[0][1])))
            for t, v in s[1:]:
                path.lineTo(QPointF(X(t), Y(v)))
            p.setPen(QPen(color, 2.4))
            p.drawPath(path)
            p.drawText(m_l + w - 150, legend_y, f"━ {name}")
            legend_y += 16


class RefrigerantEditor(QDialog):
    FIELDS = [
        ("code", "Bezeichnung", "text"), ("name", "Name", "text"), ("kind", "Typ", "text"),
        ("composition", "Zusammensetzung", "text"), ("safety", "Sicherheitsgruppe", "text"),
        ("glide", "Glide (K)", "num"), ("gwp_ar4", "GWP (AR4)", "num"), ("gwp_ar5", "GWP (AR5)", "num"),
        ("odp", "ODP", "num"), ("nbp", "Normalsiedepunkt (°C)", "num"), ("t_crit", "Krit. Temperatur (°C)", "num"),
        ("p_crit", "Krit. Druck (bar)", "num"), ("oils", "Öle", "text"), ("usage", "Einsatzbereich", "text"),
        ("status", "Status / Vorschriften", "long"), ("coolprop", "CoolProp-Name", "text"),
        ("notes", "Hinweise", "long"),
    ]

    def __init__(self, ctx: AppContext, rid: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.rid = rid
        self.setWindowTitle("Kältemittel bearbeiten" if rid else "Neues Kältemittel")
        self.resize(640, 720)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.inputs = {}
        row = ctx.db.refrigerant_by_id(rid) if rid else None
        for key, label, typ in self.FIELDS:
            if typ == "long":
                w = QTextEdit()
                w.setMaximumHeight(80)
                if row:
                    w.setPlainText(row[key] or "")
            else:
                w = QLineEdit()
                if row and row[key] is not None:
                    w.setText(str(row[key]).replace(".", ",") if typ == "num" else str(row[key]))
            if key == "coolprop":
                w.setPlaceholderText("z. B. R32, Propane, R448A.mix oder MIX:R32=0.5,R125=0.5")
            self.inputs[key] = (w, typ)
            form.addRow(label, w)
        self.verify = QCheckBox("Werte bitte prüfen")
        self.verify.setChecked(bool(row["verify"]) if row else False)
        form.addRow("", self.verify)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Speichern")
        bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def _save(self) -> None:
        data = {}
        for key, (w, typ) in self.inputs.items():
            val = w.toPlainText() if typ == "long" else w.text()
            val = val.strip()
            if typ == "num":
                if not val:
                    data[key] = None
                    continue
                try:
                    data[key] = float(val.replace(",", "."))
                except ValueError:
                    warn(self, "Ungültige Zahl", f"„{val}“ ist keine Zahl.")
                    return
            else:
                data[key] = val
        if not data["code"]:
            warn(self, "Bezeichnung fehlt", "Bitte eine Bezeichnung (z. B. R290) angeben.")
            return
        data["verify"] = 1 if self.verify.isChecked() else 0
        if self.rid:
            old = self.ctx.db.refrigerant_by_id(self.rid)
            if old and old["code"] != data["code"]:
                self.ctx.db.conn.execute("UPDATE refrigerants SET code = ? WHERE id = ?", (data["code"], self.rid))
        self.ctx.db.upsert_refrigerant(data)
        self.ctx.notify("refrigerant")
        self.accept()


class RefrigerantsPage(Page):
    COLS = [("code", "Kältemittel"), ("safety", "Sicherheit"), ("gwp_ar4", "GWP AR4"),
            ("gwp_ar5", "GWP AR5"), ("glide", "Glide K"), ("nbp", "Siedepkt. °C"), ("kind", "Typ")]

    def __init__(self, ctx: AppContext):
        super().__init__(ctx, "🧊 Kältemittel", "Stammdaten, Druck-Temperatur-Tabellen und Vergleich.")
        self.rows = []
        tabs = QTabWidget()
        self.root.addWidget(tabs, 1)

        # --- Übersicht
        overview = QWidget()
        ol = QVBoxLayout(overview)
        ol.setContentsMargins(0, 8, 0, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("🔍 Filtern (z. B. A2L, R4, Propan) …")
        self.filter.textChanged.connect(self._fill_table)
        self.safety_filter = QComboBox()
        self.safety_filter.addItem("Alle Sicherheitsgruppen", None)
        for s in ["A1", "A2L", "A3", "B2L"]:
            self.safety_filter.addItem(s, s)
        self.safety_filter.currentIndexChanged.connect(self._fill_table)
        add = QPushButton("＋ Kältemittel")
        add.clicked.connect(lambda: self._edit(None))
        ol.addLayout(hbox(self.filter, self.safety_filter, add))

        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([c[1] for c in self.COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_select)
        split.addWidget(self.table)

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(8, 0, 0, 0)
        self.d_title = QLabel("Kältemittel auswählen 👈")
        self.d_title.setObjectName("Big")
        self.d_badge = QLabel()
        dl.addLayout(hbox(self.d_title, self.d_badge, None))
        self.d_info = QLabel()
        self.d_info.setWordWrap(True)
        self.d_info.setTextFormat(Qt.RichText)
        dl.addWidget(self.d_info)
        self.btn_edit = QPushButton("✏️ Bearbeiten")
        self.btn_del = QPushButton("🗑")
        self.btn_del.setObjectName("Danger")
        self.btn_edit.clicked.connect(lambda: self._edit(self._selected_id()))
        self.btn_del.clicked.connect(self._delete)
        self.unit = QComboBox()
        self.unit.addItems(["bar(ü)", "bar(a)"])
        self.t_from = QSpinBox()
        self.t_from.setRange(-100, 150)
        self.t_from.setValue(-40)
        self.t_to = QSpinBox()
        self.t_to.setRange(-100, 200)
        self.t_to.setValue(60)
        self.t_step = QSpinBox()
        self.t_step.setRange(1, 20)
        self.t_step.setValue(5)
        for sb in (self.t_from, self.t_to, self.t_step):
            sb.setKeyboardTracking(False)
        for w in (self.unit, self.t_from, self.t_to, self.t_step):
            (w.currentIndexChanged if isinstance(w, QComboBox) else w.valueChanged).connect(self._render_pt)
        dl.addLayout(hbox(self.btn_edit, self.btn_del, None, QLabel("Von"), self.t_from, QLabel("bis"),
                          self.t_to, QLabel("°C, Schritt"), self.t_step, self.unit))
        self.chart = PTChart(ctx)
        dl.addWidget(self.chart, 1)
        self.pt = QTableWidget(0, 3)
        self.pt.setHorizontalHeaderLabels(["Temperatur °C", "Siededruck", "Taudruck"])
        self.pt.verticalHeader().setVisible(False)
        self.pt.setEditTriggers(QTableWidget.NoEditTriggers)
        self.pt.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        dl.addWidget(self.pt, 1)
        split.addWidget(detail)
        split.setSizes([560, 700])
        ol.addWidget(split, 1)
        tabs.addTab(overview, "📋 Übersicht")

        # --- Vergleich
        compare = QWidget()
        cl = QVBoxLayout(compare)
        cl.setContentsMargins(0, 8, 0, 0)
        self.cmp = [QComboBox() for _ in range(3)]
        for c in self.cmp:
            c.currentIndexChanged.connect(self._render_compare)
        cl.addLayout(hbox(QLabel("Vergleiche:"), *self.cmp, None))
        self.cmp_table = QTableWidget(0, 4)
        self.cmp_table.verticalHeader().setVisible(False)
        self.cmp_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cmp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        cl.addWidget(self.cmp_table, 1)
        self.cmp_chart = PTChart(ctx)
        cl.addWidget(self.cmp_chart, 1)
        tabs.addTab(compare, "⚖️ Vergleich")

        ctx.changed.connect(lambda k: self.refresh() if k in ("refrigerant", "all") else None)
        self.refresh()

    # ------------------------------------------------------------- Übersicht
    def refresh(self) -> None:
        self.rows = self.db.refrigerants()
        self._fill_table()
        codes = [r["code"] for r in self.rows]
        defaults = ["R404A", "R448A", "R290"]
        for i, c in enumerate(self.cmp):
            cur = c.currentText() or defaults[i]
            c.blockSignals(True)
            c.clear()
            c.addItem("—")
            c.addItems(codes)
            idx = c.findText(cur)
            c.setCurrentIndex(idx if idx >= 0 else 0)
            c.blockSignals(False)
        self._render_compare()

    def _fill_table(self) -> None:
        flt = self.filter.text().strip().lower()
        safety = self.safety_filter.currentData()
        sel = self._selected_id()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for r in self.rows:
            hay = " ".join(str(r[k] or "") for k in ("code", "name", "kind", "safety", "usage", "composition")).lower()
            if flt and flt not in hay:
                continue
            if safety and r["safety"] != safety:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, (key, _) in enumerate(self.COLS):
                val = r[key]
                item = QTableWidgetItem()
                if isinstance(val, (int, float)) and val is not None:
                    item.setData(Qt.DisplayRole, float(val))
                    item.setText(fmt(float(val), 1))
                else:
                    item.setText(str(val or "–") + (" ⚠️" if key == "code" and r["verify"] else ""))
                    if key == "code" and r["verify"]:
                        item.setToolTip("Einzelne Werte bitte prüfen")
                if key == "code":
                    item.setData(Qt.UserRole, r["id"])
                if key == "safety" and val in SAFETY_COLORS:
                    item.setForeground(QColor(SAFETY_COLORS[val]))
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        if not getattr(self, "_sorted_once", False):
            self.table.sortItems(0, Qt.AscendingOrder)
            self._sorted_once = True
        if sel:
            self.select(sel)
        elif self.table.rowCount():
            self.table.selectRow(0)

    def _selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def select(self, rid: int) -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == rid:
                self.table.selectRow(row)
                return

    def _on_select(self) -> None:
        rid = self._selected_id()
        r = self.db.refrigerant_by_id(rid) if rid else None
        if not r:
            return
        self.current = r
        self.d_title.setText(r["code"])
        col = SAFETY_COLORS.get(r["safety"], "#888")
        self.d_badge.setText(f" {r['safety'] or '?'} ")
        self.d_badge.setStyleSheet(f"background:{col}; color:white; border-radius:8px; padding:3px 10px; font-weight:700;")
        t_crit, p_crit = r["t_crit"], r["p_crit"]
        if (t_crit is None or p_crit is None) and r["coolprop"]:
            try:
                t_crit, p_crit = properties.critical_point(r["coolprop"])
            except properties.PropertyError:
                pass
        lines = [
            f"<b>{r['name']}</b> · {r['kind']}",
            f"Zusammensetzung: {r['composition'] or '–'}",
            f"GWP (AR4): <b>{fmt(r['gwp_ar4'], 0)}</b> · GWP (AR5): <b>{fmt(r['gwp_ar5'], 0)}</b> · ODP: {fmt(r['odp'], 0)}",
            f"Normalsiedepunkt: {fmt(r['nbp'], 1, '°C')} · Glide: {fmt(r['glide'], 1, 'K')} · "
            f"Kritischer Punkt: {fmt(t_crit, 1, '°C')} / {fmt(p_crit, 1, 'bar(a)')}",
            f"Öle: {r['oils'] or '–'}",
            f"Einsatz: {r['usage'] or '–'}",
            f"Status: {r['status'] or '–'}",
        ]
        if r["notes"]:
            lines.append(f"💡 {r['notes']}")
        if r["verify"]:
            lines.append("<span style='color:#F5A524'>⚠️ Einzelne Werte bitte prüfen (Datenblatt des Herstellers).</span>")
        self.d_info.setText("<br>".join(lines))
        self._render_pt()

    def _render_pt(self) -> None:
        r = getattr(self, "current", None)
        if r is None:
            return
        gauge = self.unit.currentIndex() == 0
        off = P_ATM_BAR if gauge else 0.0
        rows = properties.pt_table(r["coolprop"], self.t_from.value(), self.t_to.value(), self.t_step.value()) \
            if r["coolprop"] else []
        self.pt.setRowCount(0)
        bubble, dew = [], []
        for t, pb, pd in rows:
            i = self.pt.rowCount()
            self.pt.insertRow(i)
            self.pt.setItem(i, 0, QTableWidgetItem(fmt(float(t), 1)))
            self.pt.setItem(i, 1, QTableWidgetItem(fmt(pb - off, 2) if pb is not None else "–"))
            self.pt.setItem(i, 2, QTableWidgetItem(fmt(pd - off, 2) if pd is not None else "–"))
            if pb is not None:
                bubble.append((t, pb - off))
            if pd is not None:
                dew.append((t, pd - off))
        has_glide = any(abs(a[1] - b[1]) > 0.01 for a, b in zip(bubble, dew))
        series = [("Siedelinie", QColor("#3BA7F0"), bubble)]
        if has_glide:
            series.append(("Taulinie", QColor("#2EC4B6"), dew))
        self.pt.setHorizontalHeaderLabels(["Temperatur °C", f"Siededruck {self.unit.currentText()}",
                                           f"Taudruck {self.unit.currentText()}"])
        self.chart.set_data(series if rows else [], gauge)

    def _edit(self, rid: int | None) -> None:
        RefrigerantEditor(self.ctx, rid, self).exec()

    def _delete(self) -> None:
        rid = self._selected_id()
        r = self.db.refrigerant_by_id(rid) if rid else None
        if r and confirm(self, "Löschen", f"Kältemittel {r['code']} löschen?"):
            self.db.delete_refrigerant(rid)
            self.ctx.notify("refrigerant")

    # ------------------------------------------------------------- Vergleich
    def _render_compare(self) -> None:
        chosen = [self.db.refrigerant(c.currentText()) for c in self.cmp if c.currentText() not in ("", "—")]
        chosen = [c for c in chosen if c]
        fields = [("Name", "name", None), ("Typ", "kind", None), ("Sicherheitsgruppe", "safety", None),
                  ("GWP (AR4)", "gwp_ar4", 0), ("GWP (AR5)", "gwp_ar5", 0), ("Glide (K)", "glide", 1),
                  ("Normalsiedepunkt (°C)", "nbp", 1), ("Krit. Temperatur (°C)", "t_crit", 1),
                  ("Krit. Druck (bar)", "p_crit", 1), ("Öle", "oils", None), ("Einsatz", "usage", None)]
        self.cmp_table.setColumnCount(1 + len(chosen))
        self.cmp_table.setHorizontalHeaderLabels(["Eigenschaft"] + [c["code"] for c in chosen])
        extra = [("p bei −10 °C (Tau, bar(ü))", -10.0, 1.0), ("p bei 0 °C (Tau, bar(ü))", 0.0, 1.0),
                 ("p bei +40 °C (Siede, bar(ü))", 40.0, 0.0)]
        self.cmp_table.setRowCount(len(fields) + len(extra))
        for i, (label, key, digits) in enumerate(fields):
            self.cmp_table.setItem(i, 0, QTableWidgetItem(label))
            for j, c in enumerate(chosen):
                v = c[key]
                txt = fmt(float(v), digits) if digits is not None and v is not None else (str(v) if v else "–")
                self.cmp_table.setItem(i, j + 1, QTableWidgetItem(txt))
        for k, (label, t, q) in enumerate(extra):
            row = len(fields) + k
            self.cmp_table.setItem(row, 0, QTableWidgetItem(label))
            for j, c in enumerate(chosen):
                try:
                    txt = fmt(properties.p_sat(c["coolprop"], t, q) - P_ATM_BAR, 2)
                except properties.PropertyError:
                    txt = "–"
                self.cmp_table.setItem(row, j + 1, QTableWidgetItem(txt))
        self.cmp_table.resizeRowsToContents()
        colors = [QColor("#3BA7F0"), QColor("#F5A524"), QColor("#2EC4B6")]
        series = []
        for j, c in enumerate(chosen):
            if not c["coolprop"]:
                continue
            pts = [(t, pd - P_ATM_BAR) for t, _pb, pd in properties.pt_table(c["coolprop"], -40, 50, 5) if pd]
            series.append((c["code"], colors[j % 3], pts))
        self.cmp_chart.set_data(series, True)
