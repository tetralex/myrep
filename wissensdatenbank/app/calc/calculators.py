"""Rechner für den Werkzeugkasten. Reine Funktionen – gut testbar."""
from __future__ import annotations

from dataclasses import dataclass

from . import properties
from .units import gauge_to_abs


@dataclass
class Rating:
    level: str      # "low" | "ok" | "high"
    text: str

    @property
    def color(self) -> str:
        return {"low": "#F5A524", "ok": "#22C55E", "high": "#EF4444"}[self.level]


@dataclass
class SuperheatResult:
    t_sat: float
    value: float
    rating: Rating


# Richtwerte – immer Herstellerangaben beachten
SUPERHEAT_RANGE = (3.0, 10.0)   # K, Verdampferüberhitzung (TEV/EEV)
SUBCOOLING_RANGE = (2.0, 10.0)  # K, Unterkühlung am Verflüssigeraustritt


def _rate(value: float, lo: float, hi: float, low_text: str, ok_text: str, high_text: str) -> Rating:
    if value < lo:
        return Rating("low", low_text)
    if value > hi:
        return Rating("high", high_text)
    return Rating("ok", ok_text)


def _to_abs(p: float, gauge: bool) -> float:
    return gauge_to_abs(p) if gauge else p


def superheat(fluid: str, p_suction: float, t_pipe: float, gauge: bool = True) -> SuperheatResult:
    """Überhitzung = Rohrtemperatur Saugleitung − Taupunkttemperatur (Q=1)."""
    t_dew = properties.t_sat(fluid, _to_abs(p_suction, gauge), 1.0)
    value = t_pipe - t_dew
    lo, hi = SUPERHEAT_RANGE
    rating = _rate(
        value, lo, hi,
        "Zu niedrig – Gefahr von Flüssigkeitsschlägen. Expansionsventil/Fühler prüfen.",
        "Passt! Überhitzung im üblichen Bereich.",
        "Zu hoch – Verdampfer unterversorgt. Füllmenge, Ventil, Filtertrockner prüfen.",
    )
    return SuperheatResult(t_dew, value, rating)


def subcooling(fluid: str, p_liquid: float, t_pipe: float, gauge: bool = True) -> SuperheatResult:
    """Unterkühlung = Siedepunkttemperatur (Q=0) − Rohrtemperatur Flüssigkeitsleitung."""
    t_bubble = properties.t_sat(fluid, _to_abs(p_liquid, gauge), 0.0)
    value = t_bubble - t_pipe
    lo, hi = SUBCOOLING_RANGE
    rating = _rate(
        value, lo, hi,
        "Zu niedrig – evtl. Kältemittelmangel oder Flashgas in der Flüssigkeitsleitung.",
        "Passt! Unterkühlung im üblichen Bereich.",
        "Zu hoch – evtl. Überfüllung oder Kältemittelstau im Verflüssiger.",
    )
    return SuperheatResult(t_bubble, value, rating)


# --------------------------------------------------------------------- F-Gase
@dataclass
class LeakCheckResult:
    co2_eq_t: float
    interval: str
    interval_with_detection: str
    detection_required: bool
    note: str


def co2_equivalent(charge_kg: float, gwp: float) -> float:
    """CO₂-Äquivalent in Tonnen."""
    if charge_kg < 0:
        raise ValueError("Die Füllmenge darf nicht negativ sein.")
    if gwp < 0:
        raise ValueError("Der GWP-Wert darf nicht negativ sein.")
    return charge_kg * gwp / 1000.0


def leak_check(charge_kg: float, gwp: float, hermetic: bool = False) -> LeakCheckResult:
    """Dichtheitskontrolle nach F-Gase-VO (EU) 2024/573, Art. 5 (vereinfacht).

    Schwellen: ≥ 5 t → 12 Monate (24 mit Leckage-Erkennungssystem),
               ≥ 50 t → 6 Monate (12), ≥ 500 t → 3 Monate (6, Erkennungssystem Pflicht).
    Hermetisch geschlossene, gekennzeichnete Einrichtungen < 10 t sind ausgenommen.
    """
    t = co2_equivalent(charge_kg, gwp)
    note = ("Vereinfachte Auswertung – maßgeblich ist der Originaltext der F-Gase-VO "
            "(EU) 2024/573 inkl. Ausnahmen und GWP-Werten aus Anhang I.")
    if hermetic and t < 10:
        return LeakCheckResult(t, "keine Pflicht (hermetisch, < 10 t)", "–", False, note)
    if t < 5:
        return LeakCheckResult(t, "keine Pflicht (< 5 t CO₂-Äq.)", "–", False, note)
    if t < 50:
        return LeakCheckResult(t, "alle 12 Monate", "alle 24 Monate", False, note)
    if t < 500:
        return LeakCheckResult(t, "alle 6 Monate", "alle 12 Monate", False, note)
    return LeakCheckResult(t, "alle 3 Monate", "alle 6 Monate", True, note)


# --------------------------------------------------------------------- Kreisprozess
@dataclass
class CycleResult:
    t0: float              # Verdampfungstemperatur (Taupunkt) °C
    tc: float              # Verflüssigungstemperatur (Siedepunkt) °C
    superheat: float       # K
    subcooling: float      # K
    h1: float              # Verdichtereintritt kJ/kg
    h2: float              # Verdichteraustritt kJ/kg
    h3: float              # vor Expansionsventil kJ/kg
    q0: float              # spez. Kälteleistung kJ/kg
    w: float               # spez. Verdichterarbeit kJ/kg
    cop_cooling: float     # EER/COP Kälte
    cop_heating: float     # COP Wärme
    mass_flow: float | None = None   # kg/s (wenn Leistung angegeben)


def cycle_from_measurements(fluid: str, p_low: float, p_high: float, t_suction: float,
                            t_discharge: float, t_liquid: float, gauge: bool = True,
                            cooling_capacity_kw: float | None = None) -> CycleResult:
    """Einfache Kreisprozess-Auswertung aus Messwerten (ohne Druckverluste)."""
    pl = _to_abs(p_low, gauge)
    ph = _to_abs(p_high, gauge)
    if ph <= pl:
        raise ValueError("Der Hochdruck muss größer als der Niederdruck sein.")
    t0 = properties.t_sat(fluid, pl, 1.0)
    tc = properties.t_sat(fluid, ph, 0.0)
    sh = t_suction - t0
    sc = tc - t_liquid
    if sh <= 0:
        raise ValueError("Saugtemperatur liegt nicht über der Verdampfungstemperatur – "
                         "für die Auswertung wird überhitzter Dampf benötigt.")
    h1 = properties.enthalpy(fluid, pl, t_suction)
    h2 = properties.enthalpy(fluid, ph, t_discharge)
    h3 = properties.enthalpy(fluid, ph, t_liquid) if sc > 0.2 else properties.enthalpy_sat(fluid, ph, 0.0)
    q0 = h1 - h3
    w = h2 - h1
    if w <= 0:
        raise ValueError("Druckgastemperatur zu niedrig – Messwerte prüfen.")
    mass_flow = cooling_capacity_kw / q0 if cooling_capacity_kw else None
    return CycleResult(t0, tc, sh, sc, h1, h2, h3, q0, w, q0 / w, (q0 + w) / w, mass_flow)


def cop_from_power(output_kw: float, input_kw: float) -> float:
    if input_kw <= 0:
        raise ValueError("Die elektrische Leistung muss größer als 0 sein.")
    return output_kw / input_kw


def carnot_cop(t_evap_c: float, t_cond_c: float, heating: bool = False) -> float:
    t0 = t_evap_c + 273.15
    tc = t_cond_c + 273.15
    if tc <= t0:
        raise ValueError("Die Verflüssigungstemperatur muss über der Verdampfungstemperatur liegen.")
    return tc / (tc - t0) if heating else t0 / (tc - t0)
