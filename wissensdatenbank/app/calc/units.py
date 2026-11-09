"""Einheitenumrechnung."""
from __future__ import annotations

P_ATM_BAR = 1.01325  # Normaldruck in bar

# Faktoren auf eine Basiseinheit
PRESSURE = {  # Basis: bar
    "bar": 1.0,
    "mbar": 1e-3,
    "kPa": 1e-2,
    "MPa": 10.0,
    "Pa": 1e-5,
    "psi": 0.0689475729,
    "inHg": 0.0338638866,
    "mmHg (Torr)": 0.00133322368,
}
POWER = {  # Basis: kW
    "kW": 1.0,
    "W": 1e-3,
    "BTU/h": 0.00029307107,
    "TR (Tonne of Refrigeration)": 3.516852842,
    "kcal/h": 0.001163,
    "PS": 0.73549875,
}
VOLUME_FLOW = {  # Basis: m³/h
    "m³/h": 1.0,
    "l/s": 3.6,
    "l/min": 0.06,
    "m³/s": 3600.0,
    "CFM (ft³/min)": 1.69901082,
}
LENGTH = {  # Basis: mm
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "Zoll (inch)": 25.4,
    "Fuß (ft)": 304.8,
}
MASS = {  # Basis: kg
    "kg": 1.0,
    "g": 1e-3,
    "lb": 0.45359237,
    "oz": 0.028349523125,
}
ENERGY = {  # Basis: kWh
    "kWh": 1.0,
    "MJ": 1 / 3.6,
    "kJ": 1 / 3600,
    "BTU": 0.00029307107,
    "kcal": 0.001163,
}

CATEGORIES: dict[str, dict[str, float]] = {
    "Druck": PRESSURE,
    "Leistung": POWER,
    "Volumenstrom": VOLUME_FLOW,
    "Länge": LENGTH,
    "Masse": MASS,
    "Energie": ENERGY,
}

TEMPERATURE_UNITS = ["°C", "°F", "K"]


def convert(value: float, unit_from: str, unit_to: str, category: str) -> float:
    if category == "Temperatur":
        return convert_temperature(value, unit_from, unit_to)
    table = CATEGORIES[category]
    return value * table[unit_from] / table[unit_to]


def convert_temperature(value: float, unit_from: str, unit_to: str) -> float:
    if unit_from == "°C":
        c = value
    elif unit_from == "°F":
        c = (value - 32) * 5 / 9
    elif unit_from == "K":
        c = value - 273.15
    else:
        raise ValueError(f"Unbekannte Einheit: {unit_from}")
    if unit_to == "°C":
        return c
    if unit_to == "°F":
        return c * 9 / 5 + 32
    if unit_to == "K":
        return c + 273.15
    raise ValueError(f"Unbekannte Einheit: {unit_to}")


def gauge_to_abs(p_bar_g: float) -> float:
    return p_bar_g + P_ATM_BAR


def abs_to_gauge(p_bar_a: float) -> float:
    return p_bar_a - P_ATM_BAR


def unit_names(category: str) -> list[str]:
    if category == "Temperatur":
        return TEMPERATURE_UNITS
    return list(CATEGORIES[category])
