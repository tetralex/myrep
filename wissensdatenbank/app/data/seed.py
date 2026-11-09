"""Befüllt eine leere Datenbank mit Startinhalten."""
from __future__ import annotations

from ..core.db import Database
from .seed_articles import ARTICLES, CATEGORIES
from .seed_misc import FAULTS, GLOSSARY
from .seed_refrigerants import REFRIGERANTS

TIPS = [
    "Monteurhilfe zeigt bar(ü) – Stoffdaten brauchen bar(a). Im Rechner einfach umschalten.",
    "Zeotrope Gemische immer flüssig befüllen, sonst entmischt sich das Kältemittel.",
    "Filtertrockner nach jedem Öffnen des Kreislaufs tauschen.",
    "POE-Öl zieht Wasser – Gebinde sofort wieder verschließen.",
    "Überhitzung auf den Taupunkt, Unterkühlung auf den Siedepunkt beziehen.",
    "Rohrfühler immer isolieren – sonst misst du die Umgebung mit.",
    "Bei R744: erst dampfförmig über 5,2 bar(a) füllen, sonst bildet sich Trockeneis.",
    "Sicherheitseinrichtungen nie überbrücken – Ursache suchen statt quittieren.",
    "Vakuummeter an die Anlage, nicht an die Pumpe – sonst misst du nur die Pumpe.",
    "Strg+K öffnet überall die Schnellsuche.",
    "Eigene Unterlagen (PDF, Word, Bilder) kannst du unter „Wissen importieren“ einfach hineinziehen.",
    "Messwerte von der Baustelle direkt als Notiz im Baustellen-Log speichern.",
]


def seed(db: Database) -> None:
    cat_ids: dict[str, int] = {}
    for i, name in enumerate(CATEGORIES):
        cat_ids[name] = db.add_category(name, sort=i)

    title_ids: dict[str, int] = {}
    for cat, title, tags, body in ARTICLES:
        title_ids[title] = db.save_article(title, body.strip() + "\n", cat_ids.get(cat), tags,
                                           source="Startinhalt")

    links = [
        ("Der Kältekreislauf", "Überhitzung und Unterkühlung richtig messen"),
        ("Der Kältekreislauf", "Das log p-h-Diagramm lesen"),
        ("Überhitzung und Unterkühlung richtig messen", "Zeotrope Gemische und Temperaturgleit"),
        ("Überhitzung und Unterkühlung richtig messen", "Systematische Fehlersuche"),
        ("Sicherheitsgruppen der Kältemittel", "EN 378 – Überblick"),
        ("Druckprüfung, Dichtheitsprüfung und Evakuieren", "Checkliste Inbetriebnahme"),
        ("Kältemittel rückgewinnen", "F-Gase-Verordnung (EU) 2024/573 – Überblick"),
        ("Expansionsventile: TEV und EEV", "Überhitzung und Unterkühlung richtig messen"),
    ]
    for a, b in links:
        if a in title_ids and b in title_ids:
            db.link_articles(title_ids[a], title_ids[b])

    for r in REFRIGERANTS:
        db.upsert_refrigerant(r)

    for term, definition, article_title in GLOSSARY:
        db.save_glossary(term, definition, title_ids.get(article_title) if article_title else None)

    for f in FAULTS:
        db.save_fault(f["symptom"], f["area"], f["description"], f["causes"])

    db.set_setting("tips", TIPS)
    db.conn.commit()
