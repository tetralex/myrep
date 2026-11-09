"""Tests für den Chat-Assistenten (offline und KI-Modus mit simuliertem Client)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.calc import properties
from app.core import assistant as core
from app.core import local_config
from app.core.db import Database
from app.data.seed import seed

needs_coolprop = pytest.mark.skipif(not properties.HAVE_COOLPROP, reason="CoolProp nicht installiert")


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "t.db", tmp_path / "anhaenge")
    seed(d)
    yield d
    d.close()


@pytest.fixture()
def bot(db):
    return core.OfflineAssistant(db)


# ------------------------------------------------------------------ Erkennung
def test_parse_values(db):
    p = core.parse(db, "R448A bei 3,5 bar(a) und 8 °C, 12 kg")
    assert p.refrigerants[0]["code"] == "R448A"
    assert p.pressures == [(3.5, False)]
    assert p.temperatures == [8.0]
    assert p.masses == [12.0]
    assert core.parse(db, "r 290 bei 2 bar").refrigerants[0]["code"] == "R290"
    assert core.parse(db, "R1234ze bei 10 Grad").refrigerants[0]["code"] == "R1234ze(E)"
    assert core.parse(db, "R1234yf").refrigerants[0]["code"] == "R1234yf"


# ------------------------------------------------------------------ Offline
@needs_coolprop
def test_offline_temperature_to_pressure(bot):
    a = bot.answer("Druck R290 bei 0 °C")
    assert "3,73 bar(ü)" in a.text and a.links[0].title == "R290"


@needs_coolprop
def test_offline_pressure_with_glide_and_superheat(bot):
    a = bot.answer("R448A bei 3,5 bar und 8 °C Saugleitung")
    assert "Taupunkt" in a.text and "Siedepunkt" in a.text and "Überhitzung" in a.text


def test_offline_leak_check(bot):
    a = bot.answer("Prüfpflicht 12 kg R404A")
    assert "47,06 t" in a.text and "alle 12 Monate" in a.text


def test_offline_glossary_and_article(bot):
    a = bot.answer("Was ist Glide?")
    assert a.text.startswith("📖 **Glide:**")
    assert any(l.kind == "article" for l in a.links)


def test_offline_fault(bot):
    a = bot.answer("Verdampfer vereist")
    assert "Abtauung" in a.text and a.links[0].kind == "fault"


def test_offline_or_fallback_search(bot):
    a = bot.answer("Wie stelle ich ein TEV ein?")
    assert "Expansionsventil" in a.text


def test_offline_nothing_found(bot):
    assert "nichts gefunden" in bot.answer("xyzzy quux").text
    assert bot.answer("   ").text


def test_offline_uses_own_notes(db, bot):
    db.save_note("Kühlhaus Müller", "Verdichter Bitzer tauscht Ventilplatte", site="Halle 7")
    a = bot.answer("Ventilplatte")
    assert any(l.kind == "note" for l in a.links)


def test_best_excerpt_picks_matching_section():
    body = "# A\n\nAllgemeines.\n\n## Evakuieren\n\nVakuumpumpe anschließen.\n\n## Befüllen\n\nFlüssig füllen."
    assert core.best_excerpt(body, ["evakuieren"]).startswith("## Evakuieren")


# ------------------------------------------------------------------ KI-Modus (simulierter Client)
def block(**kw):
    return SimpleNamespace(**kw)


class FakeMessages:
    """Simuliert Claude: erst Werkzeug-Aufrufe, dann eine Textantwort."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # Stand zum Zeitpunkt des Aufrufs
        return self.script.pop(0)


def fake_client(script):
    msgs = FakeMessages(script)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def test_claude_tool_loop(db):
    script = [
        block(stop_reason="tool_use", content=[
            block(type="text", text="Ich schau nach."),
            block(type="tool_use", id="t1", name="wissen_suchen", input={"suchtext": "Glide"}),
            block(type="tool_use", id="t2", name="kaeltemittel_daten", input={"code": "R448A"}),
        ]),
        block(stop_reason="end_turn", content=[block(type="text", text="Glide ist der Temperaturgleit.")]),
    ]
    client, msgs = fake_client(script)
    bot = core.ClaudeAssistant(db, client=client)
    ans = bot.answer("Was ist Glide bei R448A?")
    assert ans.text == "Glide ist der Temperaturgleit." and ans.source == "ki"
    assert any(l.title == "R448A" for l in ans.links)
    first, second = msgs.calls
    assert first["model"] == core.CLAUDE_MODEL
    assert first["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in first["betas"]
    assert "tool_choice" not in first
    results = second["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]   # alle Ergebnisse in einer Nachricht
    assert "Glide" in results[0]["content"]
    # Verlauf bleibt für Folgefragen erhalten
    assert len(bot.history) == 4
    bot.reset()
    assert bot.history == []


def test_claude_tool_error_is_reported(db):
    script = [
        block(stop_reason="tool_use", content=[block(type="tool_use", id="x", name="gibts_nicht", input={})]),
        block(stop_reason="end_turn", content=[block(type="text", text="ok")]),
    ]
    client, msgs = fake_client(script)
    core.ClaudeAssistant(db, client=client).answer("Test")
    res = msgs.calls[1]["messages"][-1]["content"][0]
    assert res["is_error"] is True


def test_claude_refusal(db):
    client, _ = fake_client([block(stop_reason="refusal", content=[])])
    ans = core.ClaudeAssistant(db, client=client).answer("…")
    assert "keine Antwort" in ans.text


@needs_coolprop
def test_wiki_tools(db):
    t = core.WikiTools(db)
    import json
    sat = json.loads(t.run("saettigung_berechnen", {"code": "R134a", "temperatur_c": 0}))
    assert sat["siededruck_bar_a"] == pytest.approx(2.93, abs=0.02)
    leak = json.loads(t.run("dichtheitskontrolle", {"code": "R404A", "fuellmenge_kg": 12}))
    assert leak["intervall"] == "alle 12 Monate"
    art = json.loads(t.run("eintrag_lesen", {"art": "article", "id": 1}))
    assert art["titel"] and art["text"]
    assert "fehler" in json.loads(t.run("kaeltemittel_daten", {"code": "R999"}))


# ------------------------------------------------------------------ Lokale Einstellungen / Speicherort
def test_local_config_and_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KAELTEWIKI_DATA_DIR", str(tmp_path / "lokal"))
    from app import config
    assert config.data_dir() == config.user_data_dir()
    local_config.set("data_dir", str(tmp_path / "zentral"))
    assert config.data_dir() == tmp_path / "zentral"
    local_config.set("data_dir", None)
    assert "data_dir" not in local_config.load()


def test_copy_to_central(db, tmp_path):
    src = tmp_path / "bild.png"
    src.write_bytes(b"x")
    aid = db.save_article("Zentral-Test", "Inhalt")
    db.add_attachment(src, article_id=aid)
    target = db.copy_to(tmp_path / "netz")
    other = Database(target, tmp_path / "netz" / "anhaenge")
    a = other.find_article_by_title("Zentral-Test")
    assert a and other.attachment_path(other.attachments(article_id=a["id"])[0]).exists()
    other.close()
