"""Lokale Einstellungen pro PC (nicht in der – evtl. zentralen – Datenbank).

Gespeichert in %APPDATA%\\KaelteWiki\\local_config.json:
  data_dir            – zentraler Speicherort der Datenbank (leer = lokal)
  anthropic_api_key   – optionaler API-Schlüssel für den KI-Assistenten
  assistant_mode      – "offline" oder "ki"
  assistant_at_start  – Assistent beim Start am Bildschirmrand öffnen
"""
from __future__ import annotations

import json
from typing import Any

from ..config import user_data_dir


def _path():
    return user_data_dir() / "local_config.json"


def load() -> dict[str, Any]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set(key: str, value: Any) -> None:  # noqa: A001 - bewusst kurz
    data = load()
    if value is None or value == "":
        data.pop(key, None)
    else:
        data[key] = value
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_path())
