"""Stoffdaten der Kältemittel über CoolProp.

Alle Drücke in bar (absolut), Temperaturen in °C. Bei zeotropen Gemischen
wird zwischen Siedelinie (bubble, Q=0) und Taulinie (dew, Q=1) unterschieden.
Wenn CoolProp fehlt oder ein Stoff nicht berechnet werden kann, werfen die
Funktionen `PropertyError` mit einer verständlichen Meldung.
"""
from __future__ import annotations

from functools import lru_cache

try:  # CoolProp ist optional – die App läuft auch ohne
    from CoolProp.CoolProp import PropsSI  # type: ignore
    HAVE_COOLPROP = True
except Exception:  # pragma: no cover - abhängig von Installation
    PropsSI = None
    HAVE_COOLPROP = False


class PropertyError(Exception):
    pass


# Molmassen in g/mol für die Umrechnung Massen- → Molanteile
MOLAR_MASS = {
    "R32": 52.024, "R125": 120.02, "R134a": 102.03, "R143a": 84.04,
    "R1234yf": 114.04, "R1234ze(E)": 114.04, "R152a": 66.05, "R227ea": 170.03,
    "Propane": 44.10, "IsoButane": 58.12, "CO2": 44.01,
}


@lru_cache(maxsize=256)
def resolve(fluid: str) -> str:
    """Übersetzt „MIX:R32=0.5,R125=0.5“ (Massenanteile) in einen CoolProp-Gemischstring."""
    if not fluid.startswith("MIX:"):
        return fluid
    parts = []
    for item in fluid[4:].split(","):
        name, frac = item.split("=")
        name = name.strip()
        if name not in MOLAR_MASS:
            raise PropertyError(f"Komponente {name} unbekannt.")
        parts.append((name, float(frac)))
    total_mass = sum(f for _, f in parts)
    moles = [(n, (f / total_mass) / MOLAR_MASS[n]) for n, f in parts]
    total_moles = sum(m for _, m in moles)
    return "HEOS::" + "&".join(f"{n}[{m / total_moles:.6f}]" for n, m in moles)


def _props(output: str, n1: str, v1: float, n2: str, v2: float, fluid: str) -> float:
    if not HAVE_COOLPROP:
        raise PropertyError("CoolProp ist nicht installiert – keine Stoffdaten verfügbar.")
    if not fluid:
        raise PropertyError("Für dieses Kältemittel sind keine Stoffdaten hinterlegt.")
    fluid = resolve(fluid)
    try:
        value = PropsSI(output, n1, v1, n2, v2, fluid)
    except Exception as exc:  # CoolProp wirft ValueError mit langen Texten
        raise PropertyError(_friendly(str(exc))) from None
    if value != value:  # NaN
        raise PropertyError("Keine gültige Lösung für diese Eingabe.")
    return float(value)


def _friendly(msg: str) -> str:
    low = msg.lower()
    if "out of range" in low or "outside the range" in low or "is not valid" in low or "must be" in low:
        return "Wert liegt außerhalb des gültigen Bereichs (z. B. über dem kritischen Punkt)."
    if "unable to" in low or "not able" in low or "failed" in low:
        return "Berechnung nicht möglich – Eingabe prüfen (z. B. über dem kritischen Punkt)."
    return "Berechnung nicht möglich: " + msg.splitlines()[0][:160]


@lru_cache(maxsize=4096)
def t_sat(fluid: str, p_bar_abs: float, quality: float = 1.0) -> float:
    """Sättigungstemperatur in °C zu einem absoluten Druck in bar."""
    if p_bar_abs <= 0:
        raise PropertyError("Der absolute Druck muss größer als 0 sein.")
    return _props("T", "P", p_bar_abs * 1e5, "Q", quality, fluid) - 273.15


@lru_cache(maxsize=4096)
def p_sat(fluid: str, t_c: float, quality: float = 1.0) -> float:
    """Sättigungsdruck in bar(a) zu einer Temperatur in °C."""
    return _props("P", "T", t_c + 273.15, "Q", quality, fluid) / 1e5


def critical_point(fluid: str) -> tuple[float, float]:
    """(t_krit in °C, p_krit in bar)."""
    t = _props("Tcrit", "", 0, "", 0, fluid) - 273.15
    p = _props("pcrit", "", 0, "", 0, fluid) / 1e5
    return t, p


def available(fluid: str) -> bool:
    if not HAVE_COOLPROP or not fluid:
        return False
    try:
        p_sat(fluid, 0.0, 1.0)
        return True
    except PropertyError:
        return False


def pt_table(fluid: str, t_from: float = -50, t_to: float = 60, step: float = 5) -> list[tuple[float, float | None, float | None]]:
    """Druck-Temperatur-Tabelle: (t °C, p Siedelinie bar(a), p Taulinie bar(a))."""
    rows = []
    t = t_from
    while t <= t_to + 1e-9:
        try:
            pb: float | None = p_sat(fluid, round(t, 3), 0.0)
        except PropertyError:
            pb = None
        try:
            pd: float | None = p_sat(fluid, round(t, 3), 1.0)
        except PropertyError:
            pd = None
        if pb is not None or pd is not None:
            rows.append((round(t, 3), pb, pd))
        t += step
    return rows


def enthalpy(fluid: str, p_bar_abs: float, t_c: float) -> float:
    """Spezifische Enthalpie in kJ/kg (überhitzter Dampf / unterkühlte Flüssigkeit)."""
    return _props("H", "P", p_bar_abs * 1e5, "T", t_c + 273.15, fluid) / 1000


def enthalpy_sat(fluid: str, p_bar_abs: float, quality: float) -> float:
    return _props("H", "P", p_bar_abs * 1e5, "Q", quality, fluid) / 1000
