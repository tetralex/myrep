"""Zentrale Konfiguration.

Der App-Name ist ein Arbeitstitel. Um ihn zu ändern, reicht es, APP_NAME
(und optional EXE_NAME) hier anzupassen – Fenstertitel, Texte, Build-Skript
und Installer lesen den Namen von hier.

DATA_DIR_NAME bestimmt den Ordner unter %APPDATA%, in dem Datenbank,
Anhänge und Backups liegen. Wenn du ihn nachträglich änderst, beginnt die
App mit einer leeren Datenbank (alten Ordner einfach umbenennen/kopieren).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "KälteWiki"          # Anzeigename (Arbeitstitel)
EXE_NAME = "KaelteWiki"         # Dateiname der .exe (ohne Umlaute)
APP_VERSION = "1.0.0"
DATA_DIR_NAME = "KaelteWiki"    # Ordner in %APPDATA%
ORGANIZATION = "KaelteWiki"

ACCENT = "#3BA7F0"              # Eisblau
ACCENT_2 = "#2EC4B6"            # Türkis

MAX_BACKUPS = 10


def resource_path(relative: str) -> Path:
    """Pfad zu mitgelieferten Dateien – funktioniert auch in der PyInstaller-.exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if hasattr(sys, "_MEIPASS"):
        base = base / "app"
    return base / relative


def user_data_dir() -> Path:
    """Lokaler Benutzer-Ordner (%APPDATA%\\KaelteWiki unter Windows).

    Hier liegen immer die lokalen Einstellungen (local_config.json, z. B. der
    gewählte Speicherort und der API-Schlüssel). Die Wissensdatenbank selbst
    liegt hier, solange kein zentraler Speicherort gewählt wurde.
    """
    override = os.environ.get("KAELTEWIKI_DATA_DIR")
    if override:
        root = Path(override)
    elif sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home())) / DATA_DIR_NAME
    else:
        root = Path.home() / ".local" / "share" / DATA_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_dir() -> Path:
    """Ordner der Wissensdatenbank – lokal oder zentral (Netzlaufwerk, NAS, OneDrive …)."""
    from .core import local_config
    configured = local_config.load().get("data_dir")
    return Path(configured) if configured else user_data_dir()
