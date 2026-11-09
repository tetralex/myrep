"""Tests für Rechner, Einheiten, Suche, Import und Pakete."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from app.calc import calculators as calc
from app.calc import properties, units
from app.core import importer, package
from app.core.db import Database
from app.data.seed import seed

needs_coolprop = pytest.mark.skipif(not properties.HAVE_COOLPROP, reason="CoolProp nicht installiert")


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db", tmp_path / "anhaenge")
    seed(d)
    yield d
    d.close()


# ------------------------------------------------------------------ Einheiten
def test_pressure_conversion():
    assert units.convert(1, "bar", "kPa", "Druck") == pytest.approx(100)
    assert units.convert(100, "psi", "bar", "Druck") == pytest.approx(6.89476, rel=1e-4)


def test_temperature_conversion():
    assert units.convert(0, "°C", "°F", "Temperatur") == pytest.approx(32)
    assert units.convert(300, "K", "°C", "Temperatur") == pytest.approx(26.85)
    assert units.convert(212, "°F", "K", "Temperatur") == pytest.approx(373.15)


def test_power_conversion():
    assert units.convert(1, "TR (Tonne of Refrigeration)", "kW", "Leistung") == pytest.approx(3.5169, rel=1e-4)
    assert units.convert(12000, "BTU/h", "kW", "Leistung") == pytest.approx(3.5169, rel=1e-3)


def test_gauge_abs():
    assert units.gauge_to_abs(0) == pytest.approx(1.01325)
    assert units.abs_to_gauge(units.gauge_to_abs(5.5)) == pytest.approx(5.5)


# ------------------------------------------------------------------ Stoffdaten
@needs_coolprop
def test_saturation_r134a():
    # R134a: bei 0 °C ca. 2,93 bar(a)
    assert properties.p_sat("R134a", 0.0) == pytest.approx(2.93, abs=0.02)
    assert properties.t_sat("R134a", 2.928) == pytest.approx(0.0, abs=0.1)


@needs_coolprop
def test_zeotropic_glide():
    tb = properties.t_sat("R407C.mix", 5.0, 0.0)
    td = properties.t_sat("R407C.mix", 5.0, 1.0)
    assert 4 < td - tb < 8


@needs_coolprop
def test_custom_mixture_string():
    p = properties.p_sat("MIX:R32=0.5,R125=0.5", 0.0, 0.0)
    assert p == pytest.approx(8.0, abs=0.1)


@needs_coolprop
def test_pressure_error_is_friendly():
    with pytest.raises(properties.PropertyError):
        properties.t_sat("R744", 200.0)  # über dem kritischen Druck
    with pytest.raises(properties.PropertyError):
        properties.t_sat("R134a", -1.0)


# ------------------------------------------------------------------ Rechner
@needs_coolprop
def test_superheat_and_subcooling():
    r = calc.superheat("R134a", 1.9168, 7.0, gauge=True)  # p_abs ≈ 2,93 → t_dew ≈ 0 °C
    assert r.value == pytest.approx(7.0, abs=0.15)
    assert r.rating.level == "ok"
    low = calc.superheat("R134a", 1.9168, 1.0)
    assert low.rating.level == "low"
    sc = calc.subcooling("R134a", 7.86, 30.0)      # t_bubble ≈ 35 °C
    assert sc.value == pytest.approx(5.0, abs=0.3)


def test_co2_equivalent_and_leak_check():
    assert calc.co2_equivalent(10, 1430) == pytest.approx(14.3)
    assert calc.leak_check(1, 1430).interval.startswith("keine")          # 1,43 t
    assert calc.leak_check(10, 1430).interval == "alle 12 Monate"          # 14,3 t
    assert calc.leak_check(40, 1430).interval == "alle 6 Monate"           # 57,2 t
    big = calc.leak_check(200, 3922)                                       # 784 t
    assert big.interval == "alle 3 Monate" and big.detection_required
    assert calc.leak_check(5, 1430, hermetic=True).interval.startswith("keine")
    with pytest.raises(ValueError):
        calc.co2_equivalent(-1, 1430)


def test_cop_and_carnot():
    assert calc.cop_from_power(10, 4) == pytest.approx(2.5)
    with pytest.raises(ValueError):
        calc.cop_from_power(10, 0)
    assert calc.carnot_cop(-10, 40) == pytest.approx(263.15 / 50)
    with pytest.raises(ValueError):
        calc.carnot_cop(40, 10)


@needs_coolprop
def test_cycle():
    r = calc.cycle_from_measurements("R134a", 1.0, 8.0, 5.0, 60.0, 30.0)
    assert 2 < r.cop_cooling < 8
    assert r.q0 > 0 and r.w > 0
    with pytest.raises(ValueError):
        calc.cycle_from_measurements("R134a", 8.0, 1.0, 5.0, 60.0, 30.0)


# ------------------------------------------------------------------ Datenbank & Suche
def test_seed_counts(db: Database):
    s = db.stats()
    assert s["articles"] >= 15
    assert s["refrigerants"] >= 16
    assert s["faults"] >= 10
    assert s["glossary"] >= 40


def test_search_finds_umlauts_and_prefix(db: Database):
    hits = db.search("überhitz")
    assert any(h.title == "Überhitzung" for h in hits)
    assert db.search("R290")[0].title in ("R290", "Natürliche Kältemittel: R290, R744, R717")
    assert isinstance(db.search("\"*() AND OR"), list)  # Sonderzeichen führen nicht zum Absturz
    assert db.search("") == []


def test_article_versions_and_restore(db: Database):
    aid = db.save_article("Test", "Version 1")
    db.save_article("Test", "Version 2", article_id=aid)
    versions = db.versions(aid)
    assert len(versions) == 1 and versions[0]["body"] == "Version 1"
    db.restore_version(versions[0]["id"])
    assert db.article(aid)["body"] == "Version 1"


def test_categories_and_tags(db: Database):
    cid = db.find_or_create_category(["Hersteller", "Bitzer"])
    assert db.category_path(cid) == "Hersteller › Bitzer"
    db.save_article("Bitzer Ecoline", "Text", cid, "Verdichter, Bitzer")
    assert [a["title"] for a in db.articles(category_id=db.find_or_create_category(["Hersteller"]))] == ["Bitzer Ecoline"]
    assert "Bitzer" in db.all_tags()
    assert len(db.articles(tag="Bitzer")) == 1


# ------------------------------------------------------------------ Import
def test_import_markdown_and_text(db: Database, tmp_path: Path):
    md = tmp_path / "wartung.md"
    md.write_text("# Wartungsplan Kühlraum\n\nMonatlich **Verdampfer** prüfen.", encoding="utf-8")
    txt = tmp_path / "notiz_kunde.txt"
    txt.write_text("Ölwechsel nach 10.000 h", encoding="cp1252")
    res = importer.import_paths(db, [md, txt], tags="Import")
    assert res.created == ["Wartungsplan Kühlraum", "notiz kunde"]
    a = db.find_article_by_title("Wartungsplan Kühlraum")
    assert "Verdampfer" in a["body"] and "# Wartungsplan" not in a["body"]
    assert db.search("Wartungsplan")[0].title == "Wartungsplan Kühlraum"
    assert "Ölwechsel" in db.find_article_by_title("notiz kunde")["body"]


def test_import_duplicates(db: Database, tmp_path: Path):
    md = tmp_path / "a.md"
    md.write_text("# Doppelt\n\nEins", encoding="utf-8")
    importer.import_file(db, md)
    md.write_text("# Doppelt\n\nZwei", encoding="utf-8")
    assert importer.import_file(db, md, duplicates=importer.DUP_SKIP).skipped
    r = importer.import_file(db, md, duplicates=importer.DUP_RENAME)
    assert r.created == ["Doppelt (2)"]
    importer.import_file(db, md, duplicates=importer.DUP_REPLACE)
    assert "Zwei" in db.find_article_by_title("Doppelt")["body"]
    assert db.versions(db.find_article_by_title("Doppelt")["id"])


def test_import_html(db: Database, tmp_path: Path):
    html = tmp_path / "seite.html"
    html.write_text("<html><head><title>Abtauung</title><style>x{}</style></head><body>"
                    "<h1>Abtauung</h1><p>Heißgas <b>oder</b> elektrisch.</p><ul><li>Eins</li><li>Zwei</li></ul>"
                    "</body></html>", encoding="utf-8")
    res = importer.import_file(db, html)
    a = db.find_article_by_title("Abtauung")
    assert res.created == ["Abtauung"]
    assert "**oder**" in a["body"] and "- Eins" in a["body"] and "x{}" not in a["body"]
    assert db.attachments(article_id=a["id"])  # Original als Anhang


def test_import_docx(db: Database, tmp_path: Path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Inbetriebnahme Wärmepumpe", 1)
    d.add_paragraph("Vor dem Start Kurbelwannenheizung einschalten.")
    d.add_heading("Messwerte", 2)
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Größe", "Wert"
    t.cell(1, 0).text, t.cell(1, 1).text = "Überhitzung", "6 K"
    path = tmp_path / "ibn.docx"
    d.save(path)
    res = importer.import_file(db, path)
    assert res.created == ["Inbetriebnahme Wärmepumpe"]
    body = db.find_article_by_title("Inbetriebnahme Wärmepumpe")["body"]
    assert "Kurbelwannenheizung" in body and "| Überhitzung | 6 K |" in body and "### Messwerte" in body


def _simple_pdf(path: Path, text: str) -> None:
    """Erzeugt ein minimales PDF mit Standardschrift (unabhängig von installierten Schriften)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


def test_import_pdf(db: Database, tmp_path: Path):
    pytest.importorskip("pypdf")
    path = tmp_path / "datenblatt.pdf"
    _simple_pdf(path, "Datenblatt Verdichter XY - Einsatzgrenzen R290")
    res = importer.import_file(db, path)
    assert res.created == ["datenblatt"]
    a = db.find_article_by_title("datenblatt")
    assert "Einsatzgrenzen" in a["body"]
    assert db.attachments(article_id=a["id"])


def test_import_image(db: Database, tmp_path: Path):
    img = tmp_path / "typenschild.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    res = importer.import_file(db, img)
    a = db.find_article_by_title("typenschild")
    assert res.created and "![typenschild.png](" in a["body"]


def test_import_folder_creates_categories(db: Database, tmp_path: Path):
    root = tmp_path / "Unterlagen"
    (root / "Bitzer").mkdir(parents=True)
    (root / "Bitzer" / "ecoline.md").write_text("# Ecoline\n\nText", encoding="utf-8")
    (root / "allgemein.txt").write_text("Allgemeines", encoding="utf-8")
    (root / "ignore.xyz").write_text("x")
    res = importer.import_paths(db, [root])
    assert sorted(res.created) == ["Ecoline", "allgemein"]
    eco = db.find_article_by_title("Ecoline")
    assert db.category_path(eco["category_id"]) == "Unterlagen › Bitzer"


def test_import_csv_glossary_and_refrigerants(db: Database, tmp_path: Path):
    g = tmp_path / "glossar.csv"
    g.write_text("Begriff;Erklärung\nKältemittelverlagerung;Wandern von Kältemittel im Stillstand\n", encoding="utf-8")
    r = tmp_path / "km.csv"
    r.write_text("code;name;safety;gwp_ar4\nR1233zd(E);Solstice zd;A1;4,5\n", encoding="utf-8")
    importer.import_paths(db, [g, r])
    assert db.search("Kältemittelverlagerung")
    km = db.refrigerant("R1233zd(E)")
    assert km and km["gwp_ar4"] == pytest.approx(4.5)


def test_import_text(db: Database):
    res = importer.import_text(db, "# Lötregeln\n\nMit Stickstoff spülen!")
    assert res.created == ["Lötregeln"]
    assert importer.import_text(db, "   ").errors


def test_unsupported_file(db: Database, tmp_path: Path):
    f = tmp_path / "x.exe"
    f.write_bytes(b"MZ")
    assert importer.import_file(db, f).errors


# ------------------------------------------------------------------ Pakete
def test_package_roundtrip(db: Database, tmp_path: Path):
    aid = db.save_article("Paket-Test", "Inhalt", db.find_or_create_category(["Eigene"]), "x")
    att_src = tmp_path / "foto.png"
    att_src.write_bytes(b"\x89PNG....")
    db.add_attachment(att_src, article_id=aid)
    db.save_note("Baustelle", "Notiz", site="Halle 3")
    out = package.export_package(db, tmp_path / "paket.zip")
    assert zipfile.is_zipfile(out)

    other = Database(tmp_path / "other.db", tmp_path / "other_att")
    res = package.import_package(other, out)
    assert "Paket-Test" in res.created
    a = other.find_article_by_title("Paket-Test")
    assert other.category_path(a["category_id"]) == "Eigene"
    atts = other.attachments(article_id=a["id"])
    assert atts and other.attachment_path(atts[0]).exists()
    assert other.stats()["refrigerants"] == db.stats()["refrigerants"]
    # zweites Einspielen: Doppelte werden übersprungen
    res2 = package.import_package(other, out)
    assert "Paket-Test" in res2.skipped
    other.close()


def test_package_replace_and_backup_rotation(db: Database, tmp_path: Path):
    for _ in range(3):
        package.auto_backup(db, keep=2)
    assert len(package.list_backups(db)) <= 2
    backup = package.list_backups(db)[0]
    db.save_article("Nach dem Backup", "neu")
    package.import_package(db, backup, replace=True)
    assert db.find_article_by_title("Nach dem Backup") is None
    assert db.stats()["articles"] >= 15


def test_bad_package(db: Database, tmp_path: Path):
    bad = tmp_path / "kaputt.zip"
    bad.write_text("kein zip")
    assert package.import_package(db, bad).errors
