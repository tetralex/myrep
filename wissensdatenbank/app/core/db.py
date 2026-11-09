"""SQLite-Datenbank mit FTS5-Volltextsuche.

Alle Zugriffe laufen über die Klasse `Database`. Die Volltextsuche nutzt eine
gemeinsame Tabelle `search_index`, in der Artikel, Glossar, Notizen,
Kältemittel und Fehlerbilder stehen. Sie wird beim Speichern aktualisiert.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    sort INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    tags TEXT NOT NULL DEFAULT '',
    favorite INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_versions (
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    saved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_links (
    from_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    to_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    PRIMARY KEY (from_id, to_id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    note_id INTEGER REFERENCES notes(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    added TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refrigerants (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    composition TEXT NOT NULL DEFAULT '',
    glide REAL,
    safety TEXT NOT NULL DEFAULT '',
    gwp_ar4 REAL,
    gwp_ar5 REAL,
    odp REAL,
    nbp REAL,
    t_crit REAL,
    p_crit REAL,
    oils TEXT NOT NULL DEFAULT '',
    usage TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    coolprop TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    verify INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS faults (
    id INTEGER PRIMARY KEY,
    symptom TEXT NOT NULL,
    area TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS fault_causes (
    id INTEGER PRIMARY KEY,
    fault_id INTEGER NOT NULL REFERENCES faults(id) ON DELETE CASCADE,
    cause TEXT NOT NULL,
    likelihood INTEGER NOT NULL DEFAULT 2,
    checks TEXT NOT NULL DEFAULT '',
    remedy TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS glossary (
    id INTEGER PRIMARY KEY,
    term TEXT NOT NULL UNIQUE,
    definition TEXT NOT NULL DEFAULT '',
    article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    site TEXT NOT NULL DEFAULT '',
    customer TEXT NOT NULL DEFAULT '',
    refrigerant TEXT NOT NULL DEFAULT '',
    measurements TEXT NOT NULL DEFAULT '',
    article_id INTEGER REFERENCES articles(id) ON DELETE SET NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recent (
    article_id INTEGER PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    viewed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    kind UNINDEXED, ref_id UNINDEXED, title, body,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

FALLBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_index (
    kind TEXT, ref_id INTEGER, title TEXT, body TEXT
);
"""

KIND_LABELS = {
    "article": "Artikel",
    "glossary": "Glossar",
    "note": "Notiz",
    "refrigerant": "Kältemittel",
    "fault": "Fehlerbild",
}


_UMLAUT = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "Ä": "a", "Ö": "o", "Ü": "u"})


def sort_key(text: str) -> str:
    """Sortierschlüssel, der Umlaute wie Grundbuchstaben behandelt."""
    return text.translate(_UMLAUT).lower()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class SearchHit:
    kind: str
    ref_id: int
    title: str
    snippet: str

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#*_`>|]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class Database:
    def __init__(self, path: Path | str, attachments_dir: Path | None = None):
        self.path = Path(path)
        self.attachments_dir = attachments_dir or self.path.parent / "anhaenge"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        # Bei zentraler Ablage (Netzlaufwerk) kurz warten statt sofort „database is locked“
        self.conn.execute("PRAGMA busy_timeout = 15000")
        self.conn.executescript(SCHEMA)
        try:
            self.conn.executescript(FTS_SCHEMA)
            self.fts = True
        except sqlite3.OperationalError:
            self.conn.executescript(FALLBACK_SCHEMA)
            self.fts = False
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ allgemein
    def close(self) -> None:
        self.conn.close()

    def copy_to(self, target_dir: Path) -> Path:
        """Kopiert Datenbank (konsistent über die SQLite-Backup-API) und Anhänge in einen anderen Ordner."""
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / self.path.name
        dest = sqlite3.connect(str(target))
        try:
            self.conn.commit()
            self.conn.backup(dest)
        finally:
            dest.close()
        att_target = target_dir / "anhaenge"
        att_target.mkdir(exist_ok=True)
        for f in self.attachments_dir.iterdir():
            if f.is_file() and not (att_target / f.name).exists():
                shutil.copy2(f, att_target / f.name)
        return target

    def q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def is_empty(self) -> bool:
        row = self.one("SELECT COUNT(*) AS n FROM articles")
        return row is None or row["n"] == 0

    # ------------------------------------------------------------------ Einstellungen
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return default

    def set_setting(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ Suchindex
    def _index(self, kind: str, ref_id: int, title: str, body: str) -> None:
        self.conn.execute(
            "DELETE FROM search_index WHERE kind = ? AND ref_id = ?", (kind, ref_id)
        )
        self.conn.execute(
            "INSERT INTO search_index(kind, ref_id, title, body) VALUES (?, ?, ?, ?)",
            (kind, ref_id, title, _strip_markdown(body)),
        )

    def _unindex(self, kind: str, ref_id: int) -> None:
        self.conn.execute(
            "DELETE FROM search_index WHERE kind = ? AND ref_id = ?", (kind, ref_id)
        )

    def rebuild_index(self) -> None:
        self.conn.execute("DELETE FROM search_index")
        for a in self.q("SELECT * FROM articles"):
            self._index("article", a["id"], a["title"], f"{a['tags']} {a['body']}")
        for g in self.q("SELECT * FROM glossary"):
            self._index("glossary", g["id"], g["term"], g["definition"])
        for n in self.q("SELECT * FROM notes"):
            self._index("note", n["id"], n["title"],
                        f"{n['site']} {n['customer']} {n['refrigerant']} {n['body']}")
        for r in self.q("SELECT * FROM refrigerants"):
            self._index_refrigerant(r)
        for f in self.q("SELECT * FROM faults"):
            self._index_fault(f["id"])
        self.conn.commit()

    @staticmethod
    def _fts_query(text: str) -> str:
        words = re.findall(r"[\w\-]+", text, flags=re.UNICODE)
        parts = []
        for w in words:
            w = w.replace('"', "")
            if w:
                parts.append(f'"{w}"*')
        return " ".join(parts)

    def search(self, text: str, limit: int = 50, kinds: Iterable[str] | None = None) -> list[SearchHit]:
        text = text.strip()
        if not text:
            return []
        kind_filter = ""
        params: list[Any] = []
        kinds = list(kinds or [])
        rows: list[sqlite3.Row] = []
        if self.fts:
            query = self._fts_query(text)
            if not query:
                return []
            if kinds:
                kind_filter = " AND kind IN (%s)" % ",".join("?" * len(kinds))
            try:
                rows = self.q(
                    "SELECT kind, ref_id, title, "
                    "snippet(search_index, 3, '«', '»', ' … ', 12) AS snip "
                    "FROM search_index WHERE search_index MATCH ?" + kind_filter +
                    " ORDER BY bm25(search_index, 0, 0, 8.0, 1.0) LIMIT ?",
                    [query, *kinds, limit],
                )
            except sqlite3.OperationalError:
                rows = []
        if not self.fts or not rows:
            like = f"%{text}%"
            if kinds:
                kind_filter = " AND kind IN (%s)" % ",".join("?" * len(kinds))
            params = [like, like, *kinds, limit]
            rows = self.q(
                "SELECT kind, ref_id, title, substr(body, 1, 140) AS snip FROM search_index "
                "WHERE (title LIKE ? OR body LIKE ?)" + kind_filter + " LIMIT ?",
                params,
            )
        return [SearchHit(r["kind"], int(r["ref_id"]), r["title"], r["snip"] or "") for r in rows]

    # ------------------------------------------------------------------ Kategorien
    def categories(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM categories ORDER BY sort, name")

    def category_path(self, category_id: int | None) -> str:
        names = []
        seen = set()
        while category_id and category_id not in seen:
            seen.add(category_id)
            row = self.one("SELECT name, parent_id FROM categories WHERE id = ?", (category_id,))
            if not row:
                break
            names.append(row["name"])
            category_id = row["parent_id"]
        return " › ".join(reversed(names))

    def add_category(self, name: str, parent_id: int | None = None, sort: int = 0) -> int:
        cur = self.conn.execute(
            "INSERT INTO categories(name, parent_id, sort) VALUES (?, ?, ?)",
            (name.strip(), parent_id, sort),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def find_or_create_category(self, path: list[str]) -> int | None:
        parent: int | None = None
        for name in [p.strip() for p in path if p.strip()]:
            if parent is None:
                row = self.one("SELECT id FROM categories WHERE name = ? AND parent_id IS NULL", (name,))
            else:
                row = self.one("SELECT id FROM categories WHERE name = ? AND parent_id = ?", (name, parent))
            parent = int(row["id"]) if row else self.add_category(name, parent)
        return parent

    def rename_category(self, category_id: int, name: str) -> None:
        self.conn.execute("UPDATE categories SET name = ? WHERE id = ?", (name.strip(), category_id))
        self.conn.commit()

    def delete_category(self, category_id: int) -> None:
        self.conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        self.conn.commit()

    # ------------------------------------------------------------------ Artikel
    def article(self, article_id: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM articles WHERE id = ?", (article_id,))

    def articles(self, category_id: int | None = None, include_sub: bool = True,
                 favorites_only: bool = False, tag: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM articles WHERE 1=1"
        params: list[Any] = []
        if category_id is not None:
            ids = [category_id]
            if include_sub:
                ids = self._category_descendants(category_id)
            sql += " AND category_id IN (%s)" % ",".join("?" * len(ids))
            params += ids
        if favorites_only:
            sql += " AND favorite = 1"
        if tag:
            sql += " AND (',' || replace(tags, ' ', '') || ',') LIKE ?"
            params.append(f"%,{tag.replace(' ', '')},%")
        return sorted(self.q(sql, params), key=lambda r: sort_key(r["title"]))

    def _category_descendants(self, category_id: int) -> list[int]:
        result = [category_id]
        frontier = [category_id]
        while frontier:
            rows = self.q(
                "SELECT id FROM categories WHERE parent_id IN (%s)" % ",".join("?" * len(frontier)),
                frontier,
            )
            frontier = [r["id"] for r in rows if r["id"] not in result]
            result += frontier
        return result

    def all_tags(self) -> list[str]:
        tags: set[str] = set()
        for r in self.q("SELECT tags FROM articles"):
            tags.update(t.strip() for t in r["tags"].split(",") if t.strip())
        return sorted(tags, key=str.lower)

    def find_article_by_title(self, title: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM articles WHERE lower(title) = lower(?)", (title.strip(),))

    def save_article(self, title: str, body: str, category_id: int | None = None,
                     tags: str = "", article_id: int | None = None, source: str = "",
                     keep_version: bool = True) -> int:
        title = title.strip() or "Ohne Titel"
        tags = ", ".join(t.strip() for t in tags.split(",") if t.strip())
        ts = now()
        if article_id is None:
            cur = self.conn.execute(
                "INSERT INTO articles(title, body, category_id, tags, source, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (title, body, category_id, tags, source, ts, ts),
            )
            article_id = int(cur.lastrowid)
        else:
            old = self.article(article_id)
            if old and keep_version and (old["body"] != body or old["title"] != title or old["tags"] != tags):
                self.conn.execute(
                    "INSERT INTO article_versions(article_id, title, body, tags, saved_at) VALUES (?, ?, ?, ?, ?)",
                    (article_id, old["title"], old["body"], old["tags"], old["updated"]),
                )
                # nur die letzten 20 Versionen behalten
                self.conn.execute(
                    "DELETE FROM article_versions WHERE article_id = ? AND id NOT IN "
                    "(SELECT id FROM article_versions WHERE article_id = ? ORDER BY id DESC LIMIT 20)",
                    (article_id, article_id),
                )
            self.conn.execute(
                "UPDATE articles SET title = ?, body = ?, category_id = ?, tags = ?, updated = ? WHERE id = ?",
                (title, body, category_id, tags, ts, article_id),
            )
        self._index("article", article_id, title, f"{tags} {body}")
        self.conn.commit()
        return article_id

    def delete_article(self, article_id: int) -> None:
        for att in self.attachments(article_id=article_id):
            self._remove_attachment_file(att["stored_name"])
        self.conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        self._unindex("article", article_id)
        self.conn.commit()

    def toggle_favorite(self, article_id: int) -> bool:
        self.conn.execute("UPDATE articles SET favorite = 1 - favorite WHERE id = ?", (article_id,))
        self.conn.commit()
        row = self.article(article_id)
        return bool(row and row["favorite"])

    def versions(self, article_id: int) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM article_versions WHERE article_id = ? ORDER BY id DESC", (article_id,))

    def restore_version(self, version_id: int) -> int | None:
        v = self.one("SELECT * FROM article_versions WHERE id = ?", (version_id,))
        if not v:
            return None
        a = self.article(v["article_id"])
        if not a:
            return None
        return self.save_article(v["title"], v["body"], a["category_id"], v["tags"], a["id"])

    def mark_viewed(self, article_id: int) -> None:
        self.conn.execute(
            "INSERT INTO recent(article_id, viewed_at) VALUES (?, ?) "
            "ON CONFLICT(article_id) DO UPDATE SET viewed_at = excluded.viewed_at",
            (article_id, now()),
        )
        self.conn.commit()

    def recent_articles(self, limit: int = 8) -> list[sqlite3.Row]:
        return self.q(
            "SELECT a.* FROM recent r JOIN articles a ON a.id = r.article_id "
            "ORDER BY r.viewed_at DESC LIMIT ?", (limit,))

    def favorite_articles(self) -> list[sqlite3.Row]:
        return self.articles(favorites_only=True)

    # Verknüpfungen
    def links(self, article_id: int) -> list[sqlite3.Row]:
        return self.q(
            "SELECT a.* FROM articles a WHERE a.id IN ("
            "SELECT to_id FROM article_links WHERE from_id = ? "
            "UNION SELECT from_id FROM article_links WHERE to_id = ?) ORDER BY a.title",
            (article_id, article_id),
        )

    def link_articles(self, a: int, b: int) -> None:
        if a == b:
            return
        self.conn.execute("INSERT OR IGNORE INTO article_links(from_id, to_id) VALUES (?, ?)", (a, b))
        self.conn.commit()

    def unlink_articles(self, a: int, b: int) -> None:
        self.conn.execute(
            "DELETE FROM article_links WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)",
            (a, b, b, a))
        self.conn.commit()

    # ------------------------------------------------------------------ Anhänge
    def attachments(self, article_id: int | None = None, note_id: int | None = None) -> list[sqlite3.Row]:
        if article_id is not None:
            return self.q("SELECT * FROM attachments WHERE article_id = ? ORDER BY id", (article_id,))
        return self.q("SELECT * FROM attachments WHERE note_id = ? ORDER BY id", (note_id,))

    def add_attachment(self, source: Path | str, article_id: int | None = None,
                       note_id: int | None = None) -> sqlite3.Row:
        source = Path(source)
        stored = f"{uuid.uuid4().hex[:12]}_{source.name}"
        shutil.copy2(source, self.attachments_dir / stored)
        cur = self.conn.execute(
            "INSERT INTO attachments(article_id, note_id, filename, stored_name, added) VALUES (?, ?, ?, ?, ?)",
            (article_id, note_id, source.name, stored, now()),
        )
        self.conn.commit()
        return self.one("SELECT * FROM attachments WHERE id = ?", (cur.lastrowid,))  # type: ignore[return-value]

    def attachment_path(self, att: sqlite3.Row) -> Path:
        return self.attachments_dir / att["stored_name"]

    def _remove_attachment_file(self, stored_name: str) -> None:
        try:
            (self.attachments_dir / stored_name).unlink(missing_ok=True)
        except OSError:
            pass

    def delete_attachment(self, attachment_id: int) -> None:
        row = self.one("SELECT * FROM attachments WHERE id = ?", (attachment_id,))
        if row:
            self._remove_attachment_file(row["stored_name"])
            self.conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
            self.conn.commit()

    # ------------------------------------------------------------------ Kältemittel
    REFRIGERANT_FIELDS = ("code", "name", "kind", "composition", "glide", "safety", "gwp_ar4",
                          "gwp_ar5", "odp", "nbp", "t_crit", "p_crit", "oils", "usage",
                          "status", "coolprop", "notes", "verify")

    def refrigerants(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM refrigerants ORDER BY code")

    def refrigerant(self, code: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM refrigerants WHERE code = ?", (code,))

    def refrigerant_by_id(self, rid: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM refrigerants WHERE id = ?", (rid,))

    def upsert_refrigerant(self, data: dict[str, Any]) -> int:
        fields = [f for f in self.REFRIGERANT_FIELDS if f in data]
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        updates = ", ".join(f"{f} = excluded.{f}" for f in fields if f != "code")
        self.conn.execute(
            f"INSERT INTO refrigerants({cols}) VALUES ({marks}) "
            f"ON CONFLICT(code) DO UPDATE SET {updates}",
            [data[f] for f in fields],
        )
        row = self.refrigerant(data["code"])
        assert row is not None
        self._index_refrigerant(row)
        self.conn.commit()
        return int(row["id"])

    def delete_refrigerant(self, rid: int) -> None:
        self.conn.execute("DELETE FROM refrigerants WHERE id = ?", (rid,))
        self._unindex("refrigerant", rid)
        self.conn.commit()

    def _index_refrigerant(self, r: sqlite3.Row) -> None:
        body = " ".join(str(r[k] or "") for k in ("name", "kind", "composition", "safety",
                                                     "oils", "usage", "status", "notes"))
        self._index("refrigerant", r["id"], r["code"], body)

    # ------------------------------------------------------------------ Fehlerbilder
    def faults(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM faults ORDER BY area, symptom")

    def fault(self, fid: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM faults WHERE id = ?", (fid,))

    def fault_causes(self, fid: int) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM fault_causes WHERE fault_id = ? ORDER BY likelihood DESC, sort, id", (fid,))

    def save_fault(self, symptom: str, area: str, description: str,
                   causes: list[dict[str, Any]], fault_id: int | None = None) -> int:
        if fault_id is None:
            cur = self.conn.execute(
                "INSERT INTO faults(symptom, area, description) VALUES (?, ?, ?)",
                (symptom.strip(), area.strip(), description))
            fault_id = int(cur.lastrowid)
        else:
            self.conn.execute(
                "UPDATE faults SET symptom = ?, area = ?, description = ? WHERE id = ?",
                (symptom.strip(), area.strip(), description, fault_id))
            self.conn.execute("DELETE FROM fault_causes WHERE fault_id = ?", (fault_id,))
        for i, c in enumerate(causes):
            if not str(c.get("cause", "")).strip():
                continue
            self.conn.execute(
                "INSERT INTO fault_causes(fault_id, cause, likelihood, checks, remedy, sort) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (fault_id, c["cause"].strip(), int(c.get("likelihood", 2)), c.get("checks", ""),
                 c.get("remedy", ""), i))
        self._index_fault(fault_id)
        self.conn.commit()
        return fault_id

    def delete_fault(self, fid: int) -> None:
        self.conn.execute("DELETE FROM faults WHERE id = ?", (fid,))
        self._unindex("fault", fid)
        self.conn.commit()

    def _index_fault(self, fid: int) -> None:
        f = self.fault(fid)
        if not f:
            return
        body = f["area"] + " " + f["description"] + " " + " ".join(
            f"{c['cause']} {c['checks']} {c['remedy']}" for c in self.fault_causes(fid))
        self._index("fault", fid, f["symptom"], body)

    # ------------------------------------------------------------------ Glossar
    def glossary(self) -> list[sqlite3.Row]:
        return sorted(self.q("SELECT * FROM glossary"), key=lambda r: sort_key(r["term"]))

    def glossary_entry(self, gid: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM glossary WHERE id = ?", (gid,))

    def save_glossary(self, term: str, definition: str, article_id: int | None = None,
                      gid: int | None = None) -> int:
        term = term.strip()
        if gid is None:
            existing = self.one("SELECT id FROM glossary WHERE lower(term) = lower(?)", (term,))
            gid = int(existing["id"]) if existing else None
        if gid is None:
            cur = self.conn.execute(
                "INSERT INTO glossary(term, definition, article_id) VALUES (?, ?, ?)",
                (term, definition.strip(), article_id))
            gid = int(cur.lastrowid)
        else:
            self.conn.execute(
                "UPDATE glossary SET term = ?, definition = ?, article_id = ? WHERE id = ?",
                (term, definition.strip(), article_id, gid))
        self._index("glossary", gid, term, definition)
        self.conn.commit()
        return gid

    def delete_glossary(self, gid: int) -> None:
        self.conn.execute("DELETE FROM glossary WHERE id = ?", (gid,))
        self._unindex("glossary", gid)
        self.conn.commit()

    # ------------------------------------------------------------------ Notizen
    def notes(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM notes ORDER BY updated DESC")

    def note(self, nid: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM notes WHERE id = ?", (nid,))

    def save_note(self, title: str, body: str = "", site: str = "", customer: str = "",
                  refrigerant: str = "", measurements: str = "", article_id: int | None = None,
                  note_id: int | None = None) -> int:
        ts = now()
        title = title.strip() or f"Notiz vom {datetime.now():%d.%m.%Y}"
        if note_id is None:
            cur = self.conn.execute(
                "INSERT INTO notes(title, body, site, customer, refrigerant, measurements, article_id, "
                "created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (title, body, site, customer, refrigerant, measurements, article_id, ts, ts))
            note_id = int(cur.lastrowid)
        else:
            self.conn.execute(
                "UPDATE notes SET title = ?, body = ?, site = ?, customer = ?, refrigerant = ?, "
                "measurements = ?, article_id = ?, updated = ? WHERE id = ?",
                (title, body, site, customer, refrigerant, measurements, article_id, ts, note_id))
        self._index("note", note_id, title, f"{site} {customer} {refrigerant} {measurements} {body}")
        self.conn.commit()
        return note_id

    def delete_note(self, nid: int) -> None:
        for att in self.attachments(note_id=nid):
            self._remove_attachment_file(att["stored_name"])
        self.conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
        self._unindex("note", nid)
        self.conn.commit()

    # ------------------------------------------------------------------ Statistik
    def stats(self) -> dict[str, int]:
        result = {}
        for table in ("articles", "refrigerants", "faults", "glossary", "notes"):
            row = self.one(f"SELECT COUNT(*) AS n FROM {table}")
            result[table] = int(row["n"]) if row else 0
        return result
