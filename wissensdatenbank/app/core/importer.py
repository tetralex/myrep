"""Neues Wissen importieren.

Unterstützt:
  * Markdown (.md, .markdown), Text (.txt), HTML (.html, .htm)
  * PDF (.pdf, Textauszug über pypdf)
  * Word (.docx, über python-docx – Überschriften, Listen und Tabellen)
  * Bilder (.png, .jpg, .jpeg, .gif, .bmp, .webp) → Artikel mit eingebettetem Bild
  * CSV für Glossar (Begriff;Erklärung) und Kältemittel (Spalten wie in der Datenbank)
  * ganze Ordner – Unterordner werden zu Kategorien

Die Originaldatei wird auf Wunsch als Anhang am Artikel gespeichert.
"""
from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from .db import Database

TEXT_EXT = {".md", ".markdown", ".txt"}
HTML_EXT = {".html", ".htm"}
PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
CSV_EXT = {".csv"}
ARTICLE_EXT = TEXT_EXT | HTML_EXT | PDF_EXT | DOCX_EXT | IMAGE_EXT
SUPPORTED_EXT = ARTICLE_EXT | CSV_EXT

FILE_FILTER = ("Unterstützte Dateien (*.md *.markdown *.txt *.html *.htm *.pdf *.docx "
               "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.csv);;Alle Dateien (*)")

DUP_RENAME = "rename"    # als neuen Artikel mit Zusatz „(2)“ anlegen
DUP_SKIP = "skip"        # vorhandenen Artikel behalten
DUP_REPLACE = "replace"  # vorhandenen Artikel überschreiben (alte Fassung in Versionen)


class ImportError_(Exception):
    """Fehler beim Import einer Datei (eigener Name, um builtins.ImportError nicht zu verdecken)."""


@dataclass
class ImportResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    article_ids: list[int] = field(default_factory=list)

    def merge(self, other: "ImportResult") -> None:
        self.created += other.created
        self.updated += other.updated
        self.skipped += other.skipped
        self.errors += other.errors
        self.article_ids += other.article_ids

    def summary(self) -> str:
        parts = []
        if self.created:
            parts.append(f"{len(self.created)} neu")
        if self.updated:
            parts.append(f"{len(self.updated)} aktualisiert")
        if self.skipped:
            parts.append(f"{len(self.skipped)} übersprungen")
        if self.errors:
            parts.append(f"{len(self.errors)} Fehler")
        return ", ".join(parts) or "Nichts importiert"


# ----------------------------------------------------------------- Konverter
def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _title_from_markdown(text: str) -> str | None:
    for line in text.splitlines():
        m = re.match(r"^\s*#\s+(.+?)\s*#*\s*$", line)
        if m:
            return m.group(1).strip()
        if line.strip():
            break
    return None


def _drop_first_heading(text: str, title: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if re.match(r"^\s*#\s+", line) and title in line:
            return "\n".join(lines[i + 1:]).lstrip("\n")
        break
    return text


class _HtmlToMarkdown(HTMLParser):
    BLOCK = {"p", "div", "section", "article", "br", "tr", "table", "ul", "ol", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.title = ""
        self._in_title = False
        self._skip = 0
        self._href: str | None = None
        self._list: list[str] = []
        self._ol_counter: list[int] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("ul", "ol"):
            self._list.append(tag)
            self._ol_counter.append(0)
        elif tag == "li":
            indent = "  " * (len(self._list) - 1)
            if self._list and self._list[-1] == "ol":
                self._ol_counter[-1] += 1
                self.out.append(f"\n{indent}{self._ol_counter[-1]}. ")
            else:
                self.out.append(f"\n{indent}- ")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "a":
            self._href = a.get("href")
            self.out.append("[")
        elif tag in ("td", "th"):
            self.out.append(" | ")
        elif tag in self.BLOCK:
            self.out.append("\n\n" if tag != "br" else "  \n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if tag == "title":
            self._in_title = False
        elif tag in ("ul", "ol"):
            if self._list:
                self._list.pop()
                self._ol_counter.pop()
            self.out.append("\n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "a":
            self.out.append(f"]({self._href})" if self._href else "]")
            self._href = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div"):
            self.out.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        self.out.append(re.sub(r"\s+", " ", data))

    def markdown(self) -> str:
        text = "".join(self.out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(source: str) -> tuple[str, str]:
    """Gibt (Titel, Markdown) zurück."""
    parser = _HtmlToMarkdown()
    parser.feed(source)
    md = parser.markdown()
    title = html.unescape(parser.title.strip())
    return title, md


def pdf_to_markdown(path: Path) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
    except Exception:
        raise ImportError_("PDF-Import benötigt das Paket „pypdf“.") from None
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise ImportError_(f"PDF konnte nicht gelesen werden: {exc}") from None
    title = ""
    try:
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title).strip()
    except Exception:
        pass
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = re.sub(r"[ \t]+\n", "\n", text).strip()
        if text:
            pages.append(f"### Seite {i}\n\n{text}")
    if not pages:
        body = ("*Aus diesem PDF konnte kein Text gelesen werden (evtl. gescannt). "
                "Das Original ist als Anhang gespeichert.*")
    else:
        body = "\n\n".join(pages)
    return title, body


def docx_to_markdown(path: Path) -> tuple[str, str]:
    try:
        import docx  # python-docx
    except Exception:
        raise ImportError_("Word-Import benötigt das Paket „python-docx“.") from None
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ImportError_(f"Word-Datei konnte nicht gelesen werden: {exc}") from None

    title = ""
    try:
        title = (document.core_properties.title or "").strip()
    except Exception:
        pass

    from docx.table import Table
    from docx.text.paragraph import Paragraph

    lines: list[str] = []
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, document)
            text = p.text.strip()
            if not text:
                lines.append("")
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.match(r"(Heading|Überschrift)\s*(\d)", style, re.I)
            if style.lower() == "title":
                title = title or text
                continue
            if m:
                level = min(int(m.group(2)) + 1, 6)
                if not title and level == 2:
                    title = text
                    continue
                lines.append("#" * level + " " + text)
            elif "list" in style.lower() or "liste" in style.lower():
                prefix = "1." if "number" in style.lower() or "nummer" in style.lower() else "-"
                lines.append(f"{prefix} {text}")
            else:
                runs = []
                for r in p.runs:
                    t = r.text
                    if not t:
                        continue
                    if r.bold and t.strip():
                        t = f"**{t.strip()}** "
                    runs.append(t)
                lines.append("".join(runs).strip() or text)
            lines.append("")
        elif tag == "tbl":
            table = Table(child, document)
            rows = []
            for row in table.rows:
                cells = [c.text.strip().replace("\n", " ").replace("|", "/") for c in row.cells]
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                ncols = rows[0].count("|") - 1
                rows.insert(1, "|" + "---|" * ncols)
                lines += rows + [""]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return title, text


def file_to_article(path: Path) -> tuple[str, str]:
    """Liest eine Datei und gibt (Titel, Markdown-Inhalt) zurück."""
    ext = path.suffix.lower()
    fallback = path.stem.replace("_", " ").strip()
    if ext in TEXT_EXT:
        text = _read_text(path)
        title = _title_from_markdown(text) if ext != ".txt" else None
        if title:
            text = _drop_first_heading(text, title)
        return title or fallback, text.strip()
    if ext in HTML_EXT:
        title, md = html_to_markdown(_read_text(path))
        t2 = _title_from_markdown(md)
        if not title and t2:
            title = t2
            md = _drop_first_heading(md, t2)
        return title or fallback, md
    if ext in PDF_EXT:
        title, md = pdf_to_markdown(path)
        return title or fallback, md
    if ext in DOCX_EXT:
        title, md = docx_to_markdown(path)
        return title or fallback, md
    raise ImportError_(f"Dateityp „{ext}“ wird nicht unterstützt.")


# ----------------------------------------------------------------- Import
def _unique_title(db: Database, title: str) -> str:
    if not db.find_article_by_title(title):
        return title
    n = 2
    while db.find_article_by_title(f"{title} ({n})"):
        n += 1
    return f"{title} ({n})"


def save_imported_article(db: Database, title: str, body: str, category_id: int | None,
                          tags: str, source: str, duplicates: str = DUP_RENAME,
                          result: ImportResult | None = None) -> int | None:
    result = result or ImportResult()
    existing = db.find_article_by_title(title)
    if existing and duplicates == DUP_SKIP:
        result.skipped.append(f"{title} (gibt es schon)")
        return None
    if existing and duplicates == DUP_REPLACE:
        merged_tags = ", ".join(sorted({*(t.strip() for t in existing["tags"].split(",") if t.strip()),
                                        *(t.strip() for t in tags.split(",") if t.strip())}))
        aid = db.save_article(title, body, category_id if category_id is not None else existing["category_id"],
                              merged_tags, existing["id"])
        result.updated.append(title)
        result.article_ids.append(aid)
        return aid
    if existing:
        title = _unique_title(db, title)
    aid = db.save_article(title, body, category_id, tags, source=source)
    result.created.append(title)
    result.article_ids.append(aid)
    return aid


def import_file(db: Database, path: Path | str, category_id: int | None = None, tags: str = "",
                attach_original: bool = True, duplicates: str = DUP_RENAME) -> ImportResult:
    path = Path(path)
    result = ImportResult()
    ext = path.suffix.lower()
    try:
        if not path.is_file():
            raise ImportError_("Datei nicht gefunden.")
        if ext in CSV_EXT:
            result.merge(import_csv(db, path))
            return result
        if ext in IMAGE_EXT:
            title = path.stem.replace("_", " ").strip()
            aid = save_imported_article(db, title, "", category_id, tags, path.name, duplicates, result)
            if aid is not None:
                att = db.add_attachment(path, article_id=aid)
                body = f"![{att['filename']}]({att['stored_name']})\n\n*Importiertes Bild: {path.name}*"
                row = db.article(aid)
                db.save_article(row["title"], body, row["category_id"], row["tags"], aid, keep_version=False)
            return result
        if ext not in ARTICLE_EXT:
            raise ImportError_(f"Dateityp „{ext or '?'}“ wird nicht unterstützt.")
        title, body = file_to_article(path)
        if not body.strip():
            body = "*Leere Datei importiert.*"
        aid = save_imported_article(db, title, body, category_id, tags, path.name, duplicates, result)
        if aid is not None and attach_original and ext not in TEXT_EXT:
            db.add_attachment(path, article_id=aid)
    except ImportError_ as exc:
        result.errors.append(f"{path.name}: {exc}")
    except Exception as exc:  # unerwartete Fehler sollen den Import nicht abbrechen
        result.errors.append(f"{path.name}: {exc}")
    return result


def import_paths(db: Database, paths: list[Path | str], category_id: int | None = None, tags: str = "",
                 attach_original: bool = True, duplicates: str = DUP_RENAME,
                 progress: Callable[[int, int, str], None] | None = None) -> ImportResult:
    """Importiert eine Liste von Dateien und/oder Ordnern."""
    jobs: list[tuple[Path, int | None]] = []
    for p in map(Path, paths):
        if p.is_dir():
            jobs += _collect_folder(db, p, category_id)
        else:
            jobs.append((p, category_id))
    result = ImportResult()
    for i, (path, cat) in enumerate(jobs, start=1):
        if progress:
            progress(i, len(jobs), path.name)
        result.merge(import_file(db, path, cat, tags, attach_original, duplicates))
    return result


def _collect_folder(db: Database, folder: Path, base_category: int | None) -> list[tuple[Path, int | None]]:
    """Alle unterstützten Dateien; Ordnerstruktur wird zu Unterkategorien."""
    base_path: list[str] = []
    if base_category is not None:
        base_path = db.category_path(base_category).split(" › ")
    jobs = []
    for f in sorted(folder.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXT or f.name.startswith("~$"):
            continue
        rel_dirs = list(f.relative_to(folder).parent.parts)
        cat_path = base_path + [folder.name] + rel_dirs
        cat = db.find_or_create_category(cat_path)
        jobs.append((f, cat))
    return jobs


# ----------------------------------------------------------------- CSV
GLOSSARY_TERM_COLS = {"begriff", "term", "stichwort", "name"}
GLOSSARY_DEF_COLS = {"erklärung", "erklaerung", "definition", "beschreibung", "bedeutung"}


def _sniff_rows(text: str) -> list[list[str]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in row)]


def _num(value: str) -> float | None:
    value = value.strip().replace(",", ".").replace("<", "")
    if not value or value in {"-", "–"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def import_csv(db: Database, path: Path) -> ImportResult:
    result = ImportResult()
    rows = _sniff_rows(_read_text(path))
    if not rows:
        result.errors.append(f"{path.name}: Datei ist leer.")
        return result
    header = [h.strip().lower() for h in rows[0]]

    if "code" in header:  # Kältemittel
        numeric = {"glide", "gwp_ar4", "gwp_ar5", "odp", "nbp", "t_crit", "p_crit", "verify"}
        for row in rows[1:]:
            data: dict[str, object] = {}
            for col, value in zip(header, row):
                if col not in Database.REFRIGERANT_FIELDS:
                    continue
                data[col] = _num(value) if col in numeric else value.strip()
            if not data.get("code"):
                continue
            if data.get("verify") is None:
                data.pop("verify", None)
            existed = db.refrigerant(str(data["code"])) is not None
            db.upsert_refrigerant(data)
            (result.updated if existed else result.created).append(f"Kältemittel {data['code']}")
        return result

    term_i = next((i for i, h in enumerate(header) if h in GLOSSARY_TERM_COLS), None)
    def_i = next((i for i, h in enumerate(header) if h in GLOSSARY_DEF_COLS), None)
    data_rows = rows[1:]
    if term_i is None or def_i is None:  # keine Kopfzeile → Spalte 1 = Begriff, Spalte 2 = Erklärung
        term_i, def_i, data_rows = 0, 1, rows
    for row in data_rows:
        if len(row) <= max(term_i, def_i):
            continue
        term, definition = row[term_i].strip(), row[def_i].strip()
        if not term:
            continue
        existed = db.one("SELECT id FROM glossary WHERE lower(term) = lower(?)", (term,)) is not None
        db.save_glossary(term, definition)
        (result.updated if existed else result.created).append(f"Glossar: {term}")
    return result


def import_text(db: Database, text: str, title: str = "", category_id: int | None = None,
                tags: str = "", duplicates: str = DUP_RENAME) -> ImportResult:
    """Text aus der Zwischenablage / Eingabefeld als Artikel speichern."""
    result = ImportResult()
    text = text.strip()
    if not text:
        result.errors.append("Kein Text vorhanden.")
        return result
    md_title = _title_from_markdown(text)
    if not title.strip():
        title = md_title or text.splitlines()[0][:80].strip("# ").strip() or "Eingefügter Text"
    if md_title and md_title == title:
        text = _drop_first_heading(text, title)
    save_imported_article(db, title.strip(), text, category_id, tags, "Zwischenablage", duplicates, result)
    return result
