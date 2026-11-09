"""Werkzeugkasten: Rechner."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QTabWidget, QVBoxLayout, QWidget,
)

from ...calc import calculators as calc
from ...calc import properties, units
from ..widgets import AppContext, Card, Page, hbox, info, muted


def num(lo: float, hi: float, value: float, decimals: int = 2, suffix: str = "", step: float = 0.1) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    if suffix:
        s.setSuffix(" " + suffix)
    s.setMinimumWidth(150)
    s.setKeyboardTracking(False)
    return s


def f(v: float, d: int = 1) -> str:
    return f"{v:.{d}f}".replace(".", ",")


class ResultBox(QFrame):
    """Ergebnisbereich mit großer Zahl, Ampel und Aktionen."""

    def __init__(self, ctx: AppContext, title: str):
        super().__init__()
        self.ctx = ctx
        self.title = title
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        self.big = QLabel("–")
        self.big.setObjectName("Big")
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.RichText)
        self.badge = QLabel("")
        self.badge.setWordWrap(True)
        lay.addWidget(self.big)
        lay.addWidget(self.badge)
        lay.addWidget(self.detail)
        lay.addStretch(1)
        copy = QPushButton("📋 Kopieren")
        note = QPushButton("📝 Als Notiz speichern")
        copy.clicked.connect(self._copy)
        note.clicked.connect(self._note)
        lay.addLayout(hbox(copy, note, None))
        self.plain = ""

    def set_result(self, big: str, detail: str = "", rating: calc.Rating | None = None, plain: str = "") -> None:
        self.big.setText(big)
        self.detail.setText(detail)
        if rating:
            self.badge.setText(f"●  {rating.text}")
            self.badge.setStyleSheet(f"color: {rating.color}; font-weight: 600;")
        else:
            self.badge.setText("")
        self.plain = plain or f"{big}\n{detail}"
        self.big.setStyleSheet("")

    def error(self, msg: str) -> None:
        self.big.setText("🤔")
        self.badge.setText(msg)
        self.badge.setStyleSheet("color: #EF4444; font-weight: 600;")
        self.detail.setText("")
        self.plain = ""

    def _copy(self) -> None:
        if self.plain:
            QGuiApplication.clipboard().setText(self.plain)

    def _note(self) -> None:
        if not self.plain:
            return
        self.ctx.db.save_note(f"{self.title}", body="", measurements=self.plain)
        self.ctx.notify("note")
        info(self, "Gespeichert", "Ergebnis im Baustellen-Log gespeichert. 📝")


class ToolsPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, "🧮 Werkzeugkasten", "Schnell gerechnet – Richtwerte, Herstellerangaben gehen vor.")
        self.state = self.db.get_setting("calc_state", {}) or {}
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        self.ref_combos: list[QComboBox] = []
        self.tabs.addTab(self._tab_superheat(), "🌡 Überhitzung / Unterkühlung")
        self.tabs.addTab(self._tab_saturation(), "↔️ Druck ↔ Temperatur")
        self.tabs.addTab(self._tab_cycle(), "🔄 Kreisprozess / COP")
        self.tabs.addTab(self._tab_fgas(), "🌍 CO₂-Äq. && Prüfpflicht")
        self.tabs.addTab(self._tab_units(), "📐 Einheiten")
        self.tabs.setCurrentIndex(int(self.state.get("tab", 0)))
        self.tabs.currentChanged.connect(lambda i: self._remember("tab", i))
        ctx.changed.connect(lambda k: self._fill_refrigerants() if k in ("refrigerant", "all") else None)
        self._fill_refrigerants()

    # ------------------------------------------------------------ Hilfen
    def _remember(self, key, value) -> None:
        self.state[key] = value
        self.db.set_setting("calc_state", self.state)

    def _ref_combo(self, key: str) -> QComboBox:
        c = QComboBox()
        c.setMinimumWidth(170)
        c.setProperty("state_key", key)
        self.ref_combos.append(c)
        return c

    def _fill_refrigerants(self) -> None:
        rows = [r for r in self.db.refrigerants() if r["coolprop"]]
        for c in self.ref_combos:
            key = c.property("state_key")
            cur = c.currentText() or self.state.get(key, "R134a")
            c.blockSignals(True)
            c.clear()
            for r in rows:
                c.addItem(r["code"], r["coolprop"])
            idx = c.findText(cur)
            c.setCurrentIndex(idx if idx >= 0 else 0)
            c.blockSignals(False)
        for fn in (getattr(self, "_calc_sh", None), getattr(self, "_calc_sat", None),
                   getattr(self, "_calc_cycle", None)):
            if fn:
                fn()

    def _bind(self, widget, key: str, callback) -> None:
        """Wert merken + bei Änderung neu rechnen."""
        if isinstance(widget, QDoubleSpinBox):
            if key in self.state:
                widget.setValue(float(self.state[key]))
            widget.valueChanged.connect(lambda v: (self._remember(key, v), callback()))
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(lambda _i: (self._remember(key, widget.currentText()), callback()))
        elif isinstance(widget, (QCheckBox, QRadioButton)):
            if key in self.state:
                widget.setChecked(bool(self.state[key]))
            widget.toggled.connect(lambda v: (self._remember(key, v), callback()))

    def _pressure_unit(self, key: str, callback) -> tuple[QRadioButton, QRadioButton]:
        g = QRadioButton("bar(ü)")
        a = QRadioButton("bar(a)")
        g.setChecked(True)
        if self.state.get(key) is False:
            a.setChecked(True)
        g.toggled.connect(lambda v: (self._remember(key, v), callback()))
        return g, a

    # ------------------------------------------------------------ Überhitzung
    def _tab_superheat(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setSpacing(16)

        sh_card = Card("Überhitzung", "🔥")
        form = QFormLayout()
        self.sh_ref = self._ref_combo("sh_ref")
        self.sh_p = num(-1, 150, 2.0, suffix="bar")
        self.sh_t = num(-100, 150, 7.0, 1, "°C", 0.5)
        self.sh_g, sh_a = self._pressure_unit("sh_gauge", lambda: self._calc_sh())
        form.addRow("Kältemittel", self.sh_ref)
        form.addRow("Saugdruck", self.sh_p)
        form.addRow("", hbox(self.sh_g, sh_a, None))
        form.addRow("Rohrtemperatur Saugleitung", self.sh_t)
        sh_card.lay.addLayout(form)
        sh_card.lay.addWidget(muted("Überhitzung = Rohrtemperatur − Taupunkttemperatur (Q = 1)"))
        self.sh_res = ResultBox(self.ctx, "Überhitzung")
        grid.addWidget(sh_card, 0, 0)
        grid.addWidget(self.sh_res, 0, 1)

        sc_card = Card("Unterkühlung", "❄️")
        form2 = QFormLayout()
        self.sc_p = num(-1, 150, 8.0, suffix="bar")
        self.sc_t = num(-100, 150, 31.0, 1, "°C", 0.5)
        self.sc_g, sc_a = self._pressure_unit("sc_gauge", lambda: self._calc_sh())
        form2.addRow("Hochdruck", self.sc_p)
        form2.addRow("", hbox(self.sc_g, sc_a, None))
        form2.addRow("Rohrtemperatur Flüssigkeitsleitung", self.sc_t)
        sc_card.lay.addLayout(form2)
        sc_card.lay.addWidget(muted("Unterkühlung = Siedepunkttemperatur (Q = 0) − Rohrtemperatur"))
        self.sc_res = ResultBox(self.ctx, "Unterkühlung")
        grid.addWidget(sc_card, 1, 0)
        grid.addWidget(self.sc_res, 1, 1)

        for wd, k in ((self.sh_p, "sh_p"), (self.sh_t, "sh_t"), (self.sc_p, "sc_p"), (self.sc_t, "sc_t"),
                      (self.sh_ref, "sh_ref")):
            self._bind(wd, k, self._calc_sh)
        return w

    def _calc_sh(self) -> None:
        fluid = self.sh_ref.currentData()
        name = self.sh_ref.currentText()
        if not fluid:
            return
        unit = "bar(ü)" if self.sh_g.isChecked() else "bar(a)"
        try:
            r = calc.superheat(fluid, self.sh_p.value(), self.sh_t.value(), self.sh_g.isChecked())
            self.sh_res.set_result(f"{f(r.value)} K",
                             f"Taupunkttemperatur bei {f(self.sh_p.value(), 2)} {unit}: <b>{f(r.t_sat)} °C</b>",
                             r.rating,
                             f"Überhitzung {name}: {f(r.value)} K (p = {f(self.sh_p.value(), 2)} {unit}, "
                             f"t_Rohr = {f(self.sh_t.value())} °C, t_Tau = {f(r.t_sat)} °C)")
        except (properties.PropertyError, ValueError) as e:
            self.sh_res.error(str(e))
        unit2 = "bar(ü)" if self.sc_g.isChecked() else "bar(a)"
        try:
            r = calc.subcooling(fluid, self.sc_p.value(), self.sc_t.value(), self.sc_g.isChecked())
            self.sc_res.set_result(f"{f(r.value)} K",
                             f"Siedepunkttemperatur bei {f(self.sc_p.value(), 2)} {unit2}: <b>{f(r.t_sat)} °C</b>",
                             r.rating,
                             f"Unterkühlung {name}: {f(r.value)} K (p = {f(self.sc_p.value(), 2)} {unit2}, "
                             f"t_Rohr = {f(self.sc_t.value())} °C, t_Siede = {f(r.t_sat)} °C)")
        except (properties.PropertyError, ValueError) as e:
            self.sc_res.error(str(e))

    # ------------------------------------------------------------ Sättigung
    def _tab_saturation(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setSpacing(16)
        card = Card("Sättigungswerte", "↔️")
        form = QFormLayout()
        self.sat_ref = self._ref_combo("sat_ref")
        self.sat_mode = QComboBox()
        self.sat_mode.addItems(["Druck → Temperatur", "Temperatur → Druck"])
        self.sat_p = num(-1, 200, 5.0, suffix="bar")
        self.sat_t = num(-100, 150, 0.0, 1, "°C", 0.5)
        self.sat_g, sat_a = self._pressure_unit("sat_gauge", lambda: self._calc_sat())
        form.addRow("Kältemittel", self.sat_ref)
        form.addRow("Richtung", self.sat_mode)
        form.addRow("Druck", self.sat_p)
        form.addRow("Temperatur", self.sat_t)
        form.addRow("Druckangabe", hbox(self.sat_g, sat_a, None))
        card.lay.addLayout(form)
        card.lay.addWidget(muted("Bei zeotropen Gemischen werden Siede- (bubble) und Taupunkt (dew) getrennt angezeigt."))
        card.lay.addStretch(1)
        self.sat_res = ResultBox(self.ctx, "Sättigungswerte")
        lay.addWidget(card, 1)
        lay.addWidget(self.sat_res, 1)
        self.sat_mode.setCurrentIndex(int(self.state.get("sat_mode", 0)))
        self.sat_mode.currentIndexChanged.connect(lambda i: (self._remember("sat_mode", i), self._calc_sat()))
        for wd, k in ((self.sat_p, "sat_p"), (self.sat_t, "sat_t"), (self.sat_ref, "sat_ref")):
            self._bind(wd, k, self._calc_sat)
        return w

    def _calc_sat(self) -> None:
        fluid = self.sat_ref.currentData()
        if not fluid:
            return
        gauge = self.sat_g.isChecked()
        unit = "bar(ü)" if gauge else "bar(a)"
        p_to_temp = self.sat_mode.currentIndex() == 0
        self.sat_p.setEnabled(p_to_temp)
        self.sat_t.setEnabled(not p_to_temp)
        try:
            if p_to_temp:
                p_abs = units.gauge_to_abs(self.sat_p.value()) if gauge else self.sat_p.value()
                tb = properties.t_sat(fluid, p_abs, 0.0)
                td = properties.t_sat(fluid, p_abs, 1.0)
                if abs(tb - td) < 0.05:
                    big, detail = f"{f(td)} °C", f"Sättigungstemperatur bei {f(self.sat_p.value(), 2)} {unit}"
                else:
                    big = f"{f(tb)} … {f(td)} °C"
                    detail = (f"Siedepunkt: <b>{f(tb)} °C</b> · Taupunkt: <b>{f(td)} °C</b> · "
                              f"Glide: {f(td - tb)} K")
            else:
                off = units.P_ATM_BAR if gauge else 0
                pb = properties.p_sat(fluid, self.sat_t.value(), 0.0) - off
                pd = properties.p_sat(fluid, self.sat_t.value(), 1.0) - off
                if abs(pb - pd) < 0.005:
                    big, detail = f"{f(pd, 2)} {unit}", f"Sättigungsdruck bei {f(self.sat_t.value())} °C"
                else:
                    big = f"{f(pd, 2)} … {f(pb, 2)} {unit}"
                    detail = f"Siededruck: <b>{f(pb, 2)} {unit}</b> · Taudruck: <b>{f(pd, 2)} {unit}</b>"
            self.sat_res.set_result(big, detail, plain=f"{self.sat_ref.currentText()}: {big} – " +
                              detail.replace("<b>", "").replace("</b>", ""))
        except properties.PropertyError as e:
            self.sat_res.error(str(e))

    # ------------------------------------------------------------ Kreisprozess
    def _tab_cycle(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setSpacing(16)
        card = Card("Kreisprozess aus Messwerten", "🔄")
        form = QFormLayout()
        self.cy_ref = self._ref_combo("cy_ref")
        self.cy_pl = num(-1, 150, 2.0, suffix="bar")
        self.cy_ph = num(-1, 150, 8.0, suffix="bar")
        self.cy_ts = num(-100, 150, 4.0, 1, "°C", 0.5)
        self.cy_td = num(-50, 200, 60.0, 1, "°C", 0.5)
        self.cy_tl = num(-50, 150, 31.0, 1, "°C", 0.5)
        self.cy_q = num(0, 100000, 0.0, 2, "kW", 0.5)
        self.cy_g, cy_a = self._pressure_unit("cy_gauge", lambda: self._calc_cycle())
        form.addRow("Kältemittel", self.cy_ref)
        form.addRow("Niederdruck", self.cy_pl)
        form.addRow("Hochdruck", self.cy_ph)
        form.addRow("Druckangabe", hbox(self.cy_g, cy_a, None))
        form.addRow("Sauggastemperatur (Verdichtereintritt)", self.cy_ts)
        form.addRow("Druckgastemperatur", self.cy_td)
        form.addRow("Flüssigkeitstemperatur (vor EV)", self.cy_tl)
        form.addRow("Kälteleistung (optional)", self.cy_q)
        card.lay.addLayout(form)
        card.lay.addWidget(muted("Vereinfachte Auswertung ohne Druckverluste und Wärmeverluste am Verdichter."))

        cop = Card("COP aus Leistungen", "⚡")
        f2 = QFormLayout()
        self.cop_out = num(0, 100000, 10.0, 2, "kW")
        self.cop_in = num(0, 100000, 3.0, 2, "kW")
        self.cop_res = QLabel("–")
        self.cop_res.setObjectName("Big")
        f2.addRow("Nutzleistung (Kälte/Wärme)", self.cop_out)
        f2.addRow("Elektrische Leistung", self.cop_in)
        cop.lay.addLayout(f2)
        cop.lay.addWidget(self.cop_res)
        for wd, k in ((self.cop_out, "cop_out"), (self.cop_in, "cop_in")):
            self._bind(wd, k, self._calc_cop)

        left = QVBoxLayout()
        left.addWidget(card)
        left.addWidget(cop)
        left.addStretch(1)
        self.cy_res = ResultBox(self.ctx, "Kreisprozess")
        lay.addLayout(left, 1)
        lay.addWidget(self.cy_res, 1)
        for wd, k in ((self.cy_pl, "cy_pl"), (self.cy_ph, "cy_ph"), (self.cy_ts, "cy_ts"), (self.cy_td, "cy_td"),
                      (self.cy_tl, "cy_tl"), (self.cy_q, "cy_q"), (self.cy_ref, "cy_ref")):
            self._bind(wd, k, self._calc_cycle)
        self._calc_cop()
        return w

    def _calc_cop(self) -> None:
        try:
            self.cop_res.setText(f"COP = {f(calc.cop_from_power(self.cop_out.value(), self.cop_in.value()), 2)}")
        except ValueError as e:
            self.cop_res.setText(str(e))

    def _calc_cycle(self) -> None:
        fluid = self.cy_ref.currentData()
        if not fluid:
            return
        try:
            r = calc.cycle_from_measurements(
                fluid, self.cy_pl.value(), self.cy_ph.value(), self.cy_ts.value(), self.cy_td.value(),
                self.cy_tl.value(), self.cy_g.isChecked(), self.cy_q.value() or None)
            carnot = calc.carnot_cop(r.t0, r.tc)
            rows = [
                ("Verdampfung t₀ (Tau)", f"{f(r.t0)} °C"), ("Verflüssigung t_c (Siede)", f"{f(r.tc)} °C"),
                ("Überhitzung", f"{f(r.superheat)} K"), ("Unterkühlung", f"{f(r.subcooling)} K"),
                ("h₁ Verdichtereintritt", f"{f(r.h1)} kJ/kg"), ("h₂ Verdichteraustritt", f"{f(r.h2)} kJ/kg"),
                ("h₃ vor Expansionsventil", f"{f(r.h3)} kJ/kg"),
                ("q₀ spez. Kälteleistung", f"{f(r.q0)} kJ/kg"), ("w spez. Verdichterarbeit", f"{f(r.w)} kJ/kg"),
                ("COP Kälte (EER)", f(r.cop_cooling, 2)), ("COP Wärme", f(r.cop_heating, 2)),
                ("Carnot-COP Kälte", f(carnot, 2)), ("Gütegrad", f"{f(r.cop_cooling / carnot * 100, 0)} %"),
            ]
            if r.mass_flow:
                rows.append(("Massenstrom", f"{f(r.mass_flow * 3600, 1)} kg/h"))
            html = "<table>" + "".join(f"<tr><td>{a}</td><td style='padding-left:16px'><b>{b}</b></td></tr>"
                                       for a, b in rows) + "</table>"
            plain = f"Kreisprozess {self.cy_ref.currentText()}\n" + "\n".join(f"{a}: {b}" for a, b in rows)
            self.cy_res.set_result(f"COP {f(r.cop_cooling, 2)}", html, plain=plain)
        except (properties.PropertyError, ValueError) as e:
            self.cy_res.error(str(e))

    # ------------------------------------------------------------ F-Gase
    def _tab_fgas(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setSpacing(16)
        card = Card("CO₂-Äquivalent & Dichtheitskontrolle", "🌍")
        form = QFormLayout()
        self.fg_ref = QComboBox()
        self.fg_basis = QComboBox()
        self.fg_basis.addItems(["AR4", "AR5"])
        self.fg_gwp = num(0, 30000, 1430, 0, "", 1)
        self.fg_kg = num(0, 100000, 10.0, 2, "kg")
        self.fg_herm = QCheckBox("Hermetisch geschlossen und gekennzeichnet")
        form.addRow("Kältemittel", self.fg_ref)
        form.addRow("GWP-Basis", self.fg_basis)
        form.addRow("GWP", self.fg_gwp)
        form.addRow("Füllmenge", self.fg_kg)
        form.addRow("", self.fg_herm)
        card.lay.addLayout(form)
        card.lay.addWidget(muted("GWP wird aus der Datenbank übernommen und kann angepasst werden. "
                                 "Welche GWP-Werte rechtlich gelten, bitte im Anhang der F-Gase-VO prüfen."))
        card.lay.addStretch(1)
        self.fg_res = ResultBox(self.ctx, "CO₂-Äquivalent")
        lay.addWidget(card, 1)
        lay.addWidget(self.fg_res, 1)

        def load_refs():
            cur = self.fg_ref.currentText() or self.state.get("fg_ref", "R134a")
            self.fg_ref.blockSignals(True)
            self.fg_ref.clear()
            for r in self.db.refrigerants():
                self.fg_ref.addItem(r["code"])
            idx = self.fg_ref.findText(cur)
            self.fg_ref.setCurrentIndex(max(idx, 0))
            self.fg_ref.blockSignals(False)
            take_gwp()

        def take_gwp():
            r = self.db.refrigerant(self.fg_ref.currentText())
            if r:
                v = r["gwp_ar4"] if self.fg_basis.currentText() == "AR4" else r["gwp_ar5"]
                if v is None:
                    v = r["gwp_ar4"] or 0
                self.fg_gwp.setValue(float(v))
            self._remember("fg_ref", self.fg_ref.currentText())

        self.fg_ref.currentIndexChanged.connect(lambda _i: take_gwp())
        self.fg_basis.currentIndexChanged.connect(lambda _i: take_gwp())
        self.fg_gwp.valueChanged.connect(lambda _v: self._calc_fgas())
        self._bind(self.fg_kg, "fg_kg", self._calc_fgas)
        self._bind(self.fg_herm, "fg_herm", self._calc_fgas)
        self.ctx.changed.connect(lambda k: load_refs() if k in ("refrigerant", "all") else None)
        load_refs()
        return w

    def _calc_fgas(self) -> None:
        try:
            r = calc.leak_check(self.fg_kg.value(), self.fg_gwp.value(), self.fg_herm.isChecked())
        except ValueError as e:
            self.fg_res.error(str(e))
            return
        level = "ok" if r.interval.startswith("keine") else ("high" if r.detection_required else "low")
        rating = calc.Rating(level, f"Dichtheitskontrolle: {r.interval}")
        detail = (f"Mit Leckage-Erkennungssystem: <b>{r.interval_with_detection}</b><br>"
                  + ("<b>Leckage-Erkennungssystem vorgeschrieben.</b><br>" if r.detection_required else "")
                  + f"<br><small>{r.note}</small>")
        self.fg_res.set_result(f"{f(r.co2_eq_t, 2)} t CO₂-Äq.", detail, rating,
                         f"{self.fg_ref.currentText()}, {f(self.fg_kg.value(), 2)} kg, GWP {f(self.fg_gwp.value(), 0)}: "
                         f"{f(r.co2_eq_t, 2)} t CO₂-Äq. – Dichtheitskontrolle {r.interval} "
                         f"(mit Erkennungssystem {r.interval_with_detection})")

    # ------------------------------------------------------------ Einheiten
    def _tab_units(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setSpacing(16)
        card = Card("Einheitenumrechner", "📐")
        form = QFormLayout()
        self.u_cat = QComboBox()
        self.u_cat.addItems(["Druck", "Temperatur", "Leistung", "Volumenstrom", "Länge", "Masse", "Energie"])
        self.u_val = num(-1e9, 1e9, 1.0, 4, "", 1)
        self.u_from = QComboBox()
        self.u_to = QComboBox()
        swap = QPushButton("⇅ Tauschen")
        form.addRow("Größe", self.u_cat)
        form.addRow("Wert", self.u_val)
        form.addRow("Von", self.u_from)
        form.addRow("Nach", self.u_to)
        card.lay.addLayout(form)
        card.lay.addWidget(swap)
        card.lay.addStretch(1)
        self.u_res = ResultBox(self.ctx, "Umrechnung")
        lay.addWidget(card, 1)
        lay.addWidget(self.u_res, 1)

        def fill_units():
            names = units.unit_names(self.u_cat.currentText())
            for c in (self.u_from, self.u_to):
                c.blockSignals(True)
                c.clear()
                c.addItems(names)
                c.blockSignals(False)
            self.u_to.setCurrentIndex(1 if len(names) > 1 else 0)
            self._calc_units()

        def do_swap():
            a, b = self.u_from.currentIndex(), self.u_to.currentIndex()
            self.u_from.setCurrentIndex(b)
            self.u_to.setCurrentIndex(a)

        self.u_cat.currentIndexChanged.connect(lambda _i: fill_units())
        self.u_from.currentIndexChanged.connect(lambda _i: self._calc_units())
        self.u_to.currentIndexChanged.connect(lambda _i: self._calc_units())
        self.u_val.valueChanged.connect(lambda _v: self._calc_units())
        swap.clicked.connect(do_swap)
        fill_units()
        return w

    def _calc_units(self) -> None:
        try:
            v = units.convert(self.u_val.value(), self.u_from.currentText(), self.u_to.currentText(),
                              self.u_cat.currentText())
        except (KeyError, ValueError) as e:
            self.u_res.error(str(e))
            return
        txt = f"{v:,.5g}".replace(",", " ").replace(".", ",")
        src = f"{self.u_val.value():g}".replace(".", ",")
        self.u_res.set_result(f"{txt} {self.u_to.currentText()}",
                        f"{src} {self.u_from.currentText()} = {txt} {self.u_to.currentText()}")
