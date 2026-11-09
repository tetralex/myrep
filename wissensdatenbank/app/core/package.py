"""Export, Import und Backup als Wissenspaket (.zip).

Aufbau eines Pakets:
    data.json          – alle Inhalte (Artikel mit Kategoriepfad, Glossar, ...)
    anhaenge/<name>    – Dateianhänge

Ein Paket kann vollständig wiederhergestellt („ersetzen“) oder in eine
bestehende Datenbank eingespielt werden („zusammenführen“) – so lässt sich
Wissen zwischen Kollegen austauschen.
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import APP_NAME, APP_VERSION, MAX_BACKUPS
from .db import Database
from .importer import DUP_REPLACE, DUP_SKIP, ImportResult, _unique_title

PACKAGE_FORMAT = 1


def _row(r) -> dict[str, Any]:
    return {k: r[k] for k in r.keys()}


def export_package(db: Database, target: Path | str, article_ids: list[int] | None = None,
                   include_notes: bool = True) -> Path:
    """Exportiert die Datenbank (oder ausgewählte Artikel) als ZIP-Paket."""
    target = Path(target)
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    full = article_ids is None
    articles = db.articles() if full else [a for a in (db.article(i) for i in article_ids) if a]
    attachment_files: list[tuple[str, Path]] = []

    data: dict[str, Any] = {
        "format": PACKAGE_FORMAT,
        "app": APP_NAME,
        "app_version": APP_VERSION,
        "exported": datetime.now().isoformat(timespec="seconds"),
        "full": full,
        "categories": [db.category_path(c["id"]).split(" › ") for c in db.categories()] if full else [],
        "articles": [],
    }
    for a in articles:
        atts = []
        for att in db.attachments(article_id=a["id"]):
            atts.append({"filename": att["filename"], "stored_name": att["stored_name"]})
            attachment_files.append((att["stored_name"], db.attachment_path(att)))
        data["articles"].append({
            "title": a["title"], "body": a["body"], "tags": a["tags"], "favorite": a["favorite"],
            "source": a["source"], "created": a["created"], "updated": a["updated"],
            "category": db.category_path(a["category_id"]).split(" › ") if a["category_id"] else [],
            "links": [l["title"] for l in db.links(a["id"])],
            "attachments": atts,
        })
    if full:
        data["glossary"] = [{"term": g["term"], "definition": g["definition"]} for g in db.glossary()]
        data["refrigerants"] = [
            {k: v for k, v in _row(r).items() if k != "id"} for r in db.refrigerants()]
        data["faults"] = [
            {"symptom": f["symptom"], "area": f["area"], "description": f["description"],
             "causes": [{k: c[k] for k in ("cause", "likelihood", "checks", "remedy")}
                        for c in db.fault_causes(f["id"])]}
            for f in db.faults()]
        if include_notes:
            data["notes"] = []
            for n in db.notes():
                atts = []
                for att in db.attachments(note_id=n["id"]):
                    atts.append({"filename": att["filename"], "stored_name": att["stored_name"]})
                    attachment_files.append((att["stored_name"], db.attachment_path(att)))
                d = {k: n[k] for k in ("title", "body", "site", "customer", "refrigerant",
                                       "measurements", "created", "updated")}
                d["attachments"] = atts
                data["notes"].append(d)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=1))
        for stored, path in attachment_files:
            if path.exists():
                zf.write(path, f"anhaenge/{stored}")
    tmp.replace(target)
    return target


def _clear(db: Database) -> None:
    for att in db.q("SELECT stored_name FROM attachments"):
        db._remove_attachment_file(att["stored_name"])
    for table in ("attachments", "article_links", "article_versions", "recent", "articles",
                  "categories", "glossary", "fault_causes", "faults", "refrigerants", "notes"):
        db.conn.execute(f"DELETE FROM {table}")
    db.conn.execute("DELETE FROM search_index")
    db.conn.commit()


def import_package(db: Database, source: Path | str, replace: bool = False,
                   duplicates: str = DUP_SKIP) -> ImportResult:
    """Spielt ein Paket ein. replace=True ersetzt die komplette Datenbank."""
    result = ImportResult()
    source = Path(source)
    try:
        zf = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        result.errors.append(f"{source.name}: kein gültiges Paket ({exc})")
        return result
    with zf:
        try:
            data = json.loads(zf.read("data.json").decode("utf-8"))
        except (KeyError, ValueError) as exc:
            result.errors.append(f"{source.name}: data.json fehlt oder ist beschädigt ({exc})")
            return result
        if int(data.get("format", 0)) > PACKAGE_FORMAT:
            result.errors.append("Das Paket stammt aus einer neueren Programmversion.")
            return result
        names = set(zf.namelist())

        def restore_attachment(att: dict[str, str], article_id=None, note_id=None) -> None:
            member = f"anhaenge/{att['stored_name']}"
            if member not in names:
                return
            target = db.attachments_dir / att["stored_name"]
            if target.exists() and not replace:
                stem = Path(att["stored_name"])
                target = db.attachments_dir / f"{stem.stem}_imp{stem.suffix}"
            target.write_bytes(zf.read(member))
            db.conn.execute(
                "INSERT INTO attachments(article_id, note_id, filename, stored_name, added) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (article_id, note_id, att["filename"], target.name))

        if replace:
            _clear(db)
            for path in data.get("categories", []):
                db.find_or_create_category(path)

        title_to_id: dict[str, int] = {}
        for a in data.get("articles", []):
            cat = db.find_or_create_category(a.get("category", [])) if a.get("category") else None
            existing = db.find_article_by_title(a["title"])
            title = a["title"]
            if existing and duplicates == DUP_SKIP:
                result.skipped.append(title)
                continue
            if existing and duplicates == DUP_REPLACE:
                aid = db.save_article(title, a["body"], cat, a.get("tags", ""), existing["id"])
                result.updated.append(title)
            else:
                if existing:
                    title = _unique_title(db, title)
                aid = db.save_article(title, a["body"], cat, a.get("tags", ""), source=a.get("source", ""))
                result.created.append(title)
            if a.get("favorite"):
                db.conn.execute("UPDATE articles SET favorite = 1 WHERE id = ?", (aid,))
            if replace and a.get("created"):
                db.conn.execute("UPDATE articles SET created = ?, updated = ? WHERE id = ?",
                                (a["created"], a.get("updated", a["created"]), aid))
            for att in a.get("attachments", []):
                restore_attachment(att, article_id=aid)
            title_to_id[a["title"]] = aid
        for a in data.get("articles", []):
            src = title_to_id.get(a["title"])
            for linked in a.get("links", []):
                dst = title_to_id.get(linked) or (db.find_article_by_title(linked) or {"id": None})["id"]
                if src and dst:
                    db.link_articles(src, dst)

        for g in data.get("glossary", []):
            exists = db.one("SELECT id FROM glossary WHERE lower(term) = lower(?)", (g["term"],))
            if exists and duplicates == DUP_SKIP and not replace:
                continue
            db.save_glossary(g["term"], g["definition"])
        for r in data.get("refrigerants", []):
            if db.refrigerant(r["code"]) and duplicates == DUP_SKIP and not replace:
                continue
            db.upsert_refrigerant(r)
        existing_faults = {f["symptom"].lower(): f["id"] for f in db.faults()}
        for f in data.get("faults", []):
            fid = existing_faults.get(f["symptom"].lower())
            if fid and duplicates == DUP_SKIP and not replace:
                continue
            db.save_fault(f["symptom"], f.get("area", ""), f.get("description", ""), f.get("causes", []),
                          fid if duplicates == DUP_REPLACE else None)
        for n in data.get("notes", []):
            nid = db.save_note(n["title"], n.get("body", ""), n.get("site", ""), n.get("customer", ""),
                               n.get("refrigerant", ""), n.get("measurements", ""))
            for att in n.get("attachments", []):
                restore_attachment(att, note_id=nid)
        db.conn.commit()
    return result


def backup_dir(db: Database) -> Path:
    d = db.path.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def auto_backup(db: Database, keep: int = MAX_BACKUPS) -> Path:
    """Backup beim Beenden; behält nur die letzten `keep` Sicherungen."""
    d = backup_dir(db)
    path = export_package(db, d / f"backup_{datetime.now():%Y-%m-%d_%H-%M-%S}.zip")
    backups = sorted(d.glob("backup_*.zip"))
    for old in backups[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def list_backups(db: Database) -> list[Path]:
    return sorted(backup_dir(db).glob("backup_*.zip"), reverse=True)
