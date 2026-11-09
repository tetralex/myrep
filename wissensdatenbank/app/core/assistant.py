"""Chat-Assistent, der auf das Wissen der App zugreift.

Zwei Modi:
  * OfflineAssistant – läuft ohne Internet. Erkennt Kältemittel, Drücke,
    Temperaturen und Füllmengen in der Frage, rechnet direkt (Sättigung,
    CO₂-Äquivalent) und sucht passende Stellen in Artikeln, Glossar,
    Fehlerbildern und Notizen.
  * ClaudeAssistant – optional, mit eigenem Anthropic-API-Schlüssel. Claude
    beantwortet die Frage in eigenen Worten und nutzt dafür Werkzeuge, die
    ausschließlich auf die lokale Wissensdatenbank und die Rechner zugreifen.

Antworten enthalten Links im Format kw:<art>:<id>, die die Oberfläche öffnet.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..calc import calculators as calc
from ..calc import properties
from ..calc.units import P_ATM_BAR
from .db import Database

CLAUDE_MODEL = "claude-opus-5-5"

STOPWORDS = set("""
der die das den dem des ein eine einer eines einem einen und oder aber wie was wo wer warum wieso
weshalb wann welche welcher welches ist sind war waren bin bist sein hat haben habe hast mit ohne
bei beim im in an am auf aus für von vom zu zum zur über unter nach vor hinter neben zwischen durch
gegen um es er sie wir ihr ich du man mir mich dir dich uns euch sich nicht kein keine noch schon
auch nur sehr mal bitte kann kannst können soll sollte muss müssen darf wird werden wurde dass
so als wenn denn doch ja nein gibt geht machen mache macht erklär erkläre erklären sag sage sagen
zeig zeige zeigen mein meine dein deine ihre seine viel viele welchen gut richtig genau eigentlich
""".split())


@dataclass
class Link:
    kind: str     # article | refrigerant | fault | glossary | note
    ref_id: int
    title: str

    @property
    def url(self) -> str:
        return f"kw:{self.kind}:{self.ref_id}"


@dataclass
class Answer:
    text: str                                   # Markdown
    links: list[Link] = field(default_factory=list)
    source: str = "offline"                     # offline | ki
    note: str = ""                              # Hinweis, z. B. Rückfall auf offline


def _fmt(v: float, d: int = 1) -> str:
    return f"{v:.{d}f}".replace(".", ",")


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _terms(question: str) -> list[str]:
    words = re.findall(r"[\wäöüÄÖÜß\-]+", question.lower())
    return [w for w in words if len(w) > 2 and w not in STOPWORDS]


# ======================================================================= Erkennung
@dataclass
class Parsed:
    refrigerants: list[Any]
    temperatures: list[float]
    pressures: list[tuple[float, bool]]     # (Wert, Überdruck?)
    masses: list[float]
    terms: list[str]


def find_refrigerants(db: Database, question: str) -> list[Any]:
    q = re.sub(r"\bR\s+(?=\d)", "R", question, flags=re.I).upper()
    found = []
    for r in sorted(db.refrigerants(), key=lambda r: -len(r["code"])):
        variants = {r["code"].upper(), r["code"].upper().replace("(E)", "")}
        for v in variants:
            if re.search(r"(?<![A-Z0-9])" + re.escape(v) + r"(?![A-Z0-9])", q):
                if not any(f["code"].upper().startswith(v) and f["code"] != r["code"] for f in found):
                    found.append(r)
                break
    return found


def parse(db: Database, question: str) -> Parsed:
    temps: list[float] = []
    for m in re.finditer(r"(-?\d+(?:[.,]\d+)?)\s*(?:°\s*C|grad\b|°(?!\s*F))", question, flags=re.I):
        temps.append(_num(m.group(1)))
    pressures = []
    for m in re.finditer(r"(-?\d+(?:[.,]\d+)?)\s*bar\s*(\(?\s*(a|abs|ü|ue|g)\s*\)?)?", question, flags=re.I):
        unit = (m.group(3) or "").lower()
        pressures.append((_num(m.group(1)), unit not in ("a", "abs")))
    masses = [_num(m) for m in re.findall(r"(\d+(?:[.,]\d+)?)\s*kg\b", question, flags=re.I)]
    return Parsed(find_refrigerants(db, question), temps, pressures, masses, _terms(question))


# ======================================================================= Offline
class OfflineAssistant:
    """Antwortet ohne Internet aus der lokalen Wissensdatenbank."""

    def __init__(self, db: Database):
        self.db = db

    def answer(self, question: str) -> Answer:
        question = question.strip()
        if not question:
            return Answer("Frag mich einfach was – z. B. *„Druck R290 bei 0 °C“* oder *„Was ist Glide?“* 🙂")
        p = parse(self.db, question)
        low = question.lower()
        parts: list[str] = []
        links: list[Link] = []

        ref = p.refrigerants[0] if p.refrigerants else None

        # --- F-Gase / CO2-Äquivalent
        if ref and p.masses and re.search(r"co2|co₂|äquivalent|aequivalent|dichtheit|prüf|pruef|leck|f-gas", low):
            gwp = ref["gwp_ar4"] or 0
            r = calc.leak_check(p.masses[0], gwp)
            parts.append(
                f"**{ref['code']}, {_fmt(p.masses[0], 2)} kg** (GWP AR4 {_fmt(gwp, 0)}):\n\n"
                f"- CO₂-Äquivalent: **{_fmt(r.co2_eq_t, 2)} t**\n"
                f"- Dichtheitskontrolle: **{r.interval}** (mit Leckage-Erkennungssystem: {r.interval_with_detection})"
                + ("\n- Leckage-Erkennungssystem ist **vorgeschrieben**." if r.detection_required else "")
                + "\n\n*Vereinfachte Auswertung nach F-Gase-VO (EU) 2024/573 – Originaltext und GWP-Basis prüfen.*")
            links.append(Link("refrigerant", ref["id"], ref["code"]))

        # --- Sättigung: Druck → Temperatur
        elif ref and p.pressures and ref["coolprop"]:
            value, gauge = p.pressures[0]
            p_abs = value + P_ATM_BAR if gauge else value
            unit = "bar(ü)" if gauge else "bar(a)"
            try:
                tb = properties.t_sat(ref["coolprop"], p_abs, 0.0)
                td = properties.t_sat(ref["coolprop"], p_abs, 1.0)
                txt = f"**{ref['code']} bei {_fmt(value, 2)} {unit}:** "
                if abs(tb - td) < 0.05:
                    txt += f"Sättigungstemperatur **{_fmt(td)} °C**"
                else:
                    txt += (f"Siedepunkt **{_fmt(tb)} °C**, Taupunkt **{_fmt(td)} °C** (Glide {_fmt(td - tb)} K).\n\n"
                            "Für die Überhitzung den Taupunkt, für die Unterkühlung den Siedepunkt verwenden.")
                if p.temperatures:
                    t = p.temperatures[0]
                    if re.search(r"saug|überhitz|ueberhitz|verdampf", low):
                        txt += f"\n\nMit {_fmt(t)} °C Rohrtemperatur: Überhitzung **{_fmt(t - td)} K**."
                    elif re.search(r"flüssig|fluessig|unterkühl|unterkuehl|verflüssig|hochdruck", low):
                        txt += f"\n\nMit {_fmt(t)} °C Rohrtemperatur: Unterkühlung **{_fmt(tb - t)} K**."
                    else:
                        txt += (f"\n\nMit {_fmt(t)} °C Rohrtemperatur: Überhitzung **{_fmt(t - td)} K** "
                                f"(Saugleitung) bzw. Unterkühlung **{_fmt(tb - t)} K** (Flüssigkeitsleitung).")
                parts.append(txt + ("\n\n*Hinweis: Ich habe den Druck als Überdruck (Manometer) gewertet. "
                                    "Für Absolutdruck „bar(a)“ schreiben.*" if gauge else ""))
            except properties.PropertyError as e:
                parts.append(f"Für {ref['code']} bei {_fmt(value, 2)} {unit} kann ich nichts berechnen: {e}")
            links.append(Link("refrigerant", ref["id"], ref["code"]))

        # --- Sättigung: Temperatur → Druck
        elif ref and p.temperatures and ref["coolprop"]:
            t = p.temperatures[0]
            try:
                pb = properties.p_sat(ref["coolprop"], t, 0.0)
                pd = properties.p_sat(ref["coolprop"], t, 1.0)
                if abs(pb - pd) < 0.005:
                    txt = (f"**{ref['code']} bei {_fmt(t)} °C:** Sättigungsdruck **{_fmt(pd - P_ATM_BAR, 2)} bar(ü)** "
                           f"({_fmt(pd, 2)} bar(a))")
                else:
                    txt = (f"**{ref['code']} bei {_fmt(t)} °C:**\n\n"
                           f"- Siededruck: **{_fmt(pb - P_ATM_BAR, 2)} bar(ü)** ({_fmt(pb, 2)} bar(a))\n"
                           f"- Taudruck: **{_fmt(pd - P_ATM_BAR, 2)} bar(ü)** ({_fmt(pd, 2)} bar(a))")
                parts.append(txt)
            except properties.PropertyError as e:
                parts.append(f"Für {ref['code']} bei {_fmt(t)} °C kann ich nichts berechnen: {e}")
            links.append(Link("refrigerant", ref["id"], ref["code"]))

        # --- Kältemittel-Steckbrief
        elif ref:
            parts.append(self._refrigerant_summary(ref))
            links.append(Link("refrigerant", ref["id"], ref["code"]))
            for other in p.refrigerants[1:3]:
                parts.append(self._refrigerant_summary(other))
                links.append(Link("refrigerant", other["id"], other["code"]))

        # --- Wissen durchsuchen (immer, außer bei reinen Rechenfragen mit Ergebnis)
        computed = bool(parts) and ref is not None and (p.pressures or p.temperatures or p.masses)
        search_text = " ".join(t for t in p.terms if not re.fullmatch(r"r\d+\w*", t)) or question
        hits = self.db.search(search_text, limit=12) if not computed else []
        if not hits and not computed and p.terms:
            hits = self._search_any(p.terms)

        # Reihenfolge: exakter Glossarbegriff, dann Artikel/Fehlerbilder, dann Rest
        term_set = {t.lower() for t in p.terms}

        def prio(h) -> int:
            if h.kind == "glossary" and h.title.lower() in term_set | {question.lower().strip(" ?!.")}:
                return 0
            return {"article": 1, "fault": 1, "glossary": 2, "note": 2, "refrigerant": 3}.get(h.kind, 4)

        hits = sorted(hits, key=prio)
        used = 0
        for h in hits:
            if used >= 2:
                break
            if h.kind == "glossary":
                g = self.db.glossary_entry(h.ref_id)
                if g:
                    parts.append(f"📖 **{g['term']}:** {g['definition']}")
                    links.append(Link("glossary", g["id"], g["term"]))
                    used += 1
            elif h.kind == "article":
                a = self.db.article(h.ref_id)
                if a:
                    excerpt = best_excerpt(a["body"], p.terms)
                    parts.append(f"📄 **Aus „{a['title']}“:**\n\n{excerpt}")
                    links.append(Link("article", a["id"], a["title"]))
                    used += 1
            elif h.kind == "fault":
                f = self.db.fault(h.ref_id)
                if f and any(t[:5] in f["symptom"].lower() for t in p.terms):
                    causes = self.db.fault_causes(f["id"])[:4]
                    lines = "\n".join(f"{i}. **{c['cause']}** – {c['checks']}" for i, c in enumerate(causes, 1))
                    parts.append(f"🩺 **{f['symptom']}** – häufige Ursachen:\n\n{lines}")
                    links.append(Link("fault", f["id"], f["symptom"]))
                    used += 1
            elif h.kind == "note":
                n = self.db.note(h.ref_id)
                if n:
                    parts.append(f"📝 **Deine Notiz „{n['title']}“** ({n['updated'][:10]}): "
                                 f"{(n['body'] or n['measurements'])[:300]}")
                    links.append(Link("note", n["id"], n["title"]))
                    used += 1
            elif h.kind == "refrigerant" and not ref:
                r = self.db.refrigerant_by_id(h.ref_id)
                if r:
                    parts.append(self._refrigerant_summary(r))
                    links.append(Link("refrigerant", r["id"], r["code"]))
                    used += 1
        for h in hits[used:used + 4]:
            if not any(l.kind == h.kind and l.ref_id == h.ref_id for l in links):
                links.append(Link(h.kind, h.ref_id, h.title))

        if not parts:
            return Answer("Dazu habe ich in deinem Wissen leider nichts gefunden 🧊\n\n"
                          "Probier andere Begriffe, oder leg das Wissen unter **„Wissen importieren“** an.")
        return Answer("\n\n".join(parts), links)

    def _search_any(self, terms: list[str]):
        """Fallback: jeden Begriff einzeln suchen, Treffer nach Häufigkeit zusammenführen."""
        score: dict[tuple[str, int], float] = {}
        first: dict[tuple[str, int], Any] = {}
        for term in terms[:6]:
            for rank, h in enumerate(self.db.search(term, limit=10)):
                key = (h.kind, h.ref_id)
                score[key] = score.get(key, 0) + 1 + (10 - rank) / 20
                first.setdefault(key, h)
        return [first[k] for k in sorted(score, key=lambda k: -score[k])][:12]

    def _refrigerant_summary(self, r) -> str:
        bits = [f"🧊 **{r['code']}** – {r['name']} ({r['kind']})",
                f"- Sicherheitsgruppe: **{r['safety'] or '–'}**",
                f"- GWP: AR4 **{_fmt(r['gwp_ar4'], 0) if r['gwp_ar4'] is not None else '–'}**, "
                f"AR5 {_fmt(r['gwp_ar5'], 0) if r['gwp_ar5'] is not None else '–'}"]
        if r["glide"]:
            bits.append(f"- Glide: ca. {_fmt(r['glide'])} K – flüssig befüllen")
        if r["nbp"] is not None:
            bits.append(f"- Normalsiedepunkt: {_fmt(r['nbp'])} °C")
        if r["oils"]:
            bits.append(f"- Öle: {r['oils']}")
        if r["usage"]:
            bits.append(f"- Einsatz: {r['usage']}")
        if r["status"]:
            bits.append(f"- Status: {r['status']}")
        if r["verify"]:
            bits.append("- ⚠️ Einzelne Werte bitte mit dem Datenblatt prüfen.")
        return "\n".join(bits)


def best_excerpt(body: str, terms: list[str], max_chars: int = 900) -> str:
    """Wählt den Abschnitt (Überschrift + Text) eines Artikels, der am besten zur Frage passt."""
    sections: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        if re.match(r"^#{1,6}\s", line) and current:
            sections.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    sections = [sec for sec in sections if sec]
    if not sections:
        return ""
    stems = [t[:5] for t in terms if t]

    def score(sec: str) -> float:
        low = sec.lower()
        head = low.splitlines()[0] if low.startswith("#") else ""
        return sum(low.count(st) + 2 * head.count(st) for st in stems)

    best = max(sections, key=score) if stems else sections[0]
    if score(best) == 0:
        best = sections[0]
    if len(best) > max_chars:
        best = best[:max_chars].rsplit(" ", 1)[0] + " …"
    return best


# ======================================================================= Claude
SYSTEM_PROMPT = """Du bist der Assistent der Kältetechnik-Wissensdatenbank „{app}“. Du hilfst Kältetechnikern \
im Büro und auf der Baustelle.

So arbeitest du:
- Antworte auf Deutsch, per Du, locker und freundlich – fachlich aber präzise, mit Einheiten (bar(ü)/bar(a) \
klar kennzeichnen, Temperaturen in °C, Temperaturdifferenzen in K).
- Stütze dich auf die Werkzeuge: Sie greifen auf die Wissensdatenbank des Nutzers (Artikel, Glossar, \
Fehlerbilder, Notizen, Kältemitteldaten) und auf Stoffdaten-Rechner zu. Suche zuerst im Wissen, bevor du \
antwortest, und rechne Drücke/Temperaturen mit dem Rechner statt sie zu schätzen.
- Nenne die Titel der Artikel, auf die du dich stützt. Wenn etwas nicht in der Wissensdatenbank steht und du \
Allgemeinwissen nutzt, sag das kurz dazu.
- Bei sicherheits- oder normrelevanten Themen (Füllmengen, Druckprüfung, F-Gase, Brennbarkeit) weise kurz \
darauf hin, dass Herstellerangaben und der Originaltext der Norm/Verordnung maßgeblich sind.
- Halte Antworten kurz und praxisnah: zuerst die Antwort, dann bei Bedarf Details als kurze Liste. \
Markdown ist erlaubt (fett, Listen, kleine Tabellen)."""

TOOLS = [
    {
        "name": "wissen_suchen",
        "description": "Volltextsuche in der Wissensdatenbank (Artikel, Glossar, Fehlerbilder, Notizen, "
                       "Kältemittel). Gibt Treffer mit Art, ID, Titel und Textausschnitt zurück. Nutze "
                       "aussagekräftige Fachbegriffe als Suchtext.",
        "input_schema": {
            "type": "object",
            "properties": {"suchtext": {"type": "string", "description": "Suchbegriffe, z. B. 'Überhitzung TEV'"}},
            "required": ["suchtext"],
        },
    },
    {
        "name": "eintrag_lesen",
        "description": "Liest einen Eintrag vollständig: Artikel (Markdown-Text), Fehlerbild (mit Ursachen, "
                       "Prüfschritten, Abhilfe), Glossarbegriff oder Notiz. IDs kommen aus wissen_suchen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "art": {"type": "string", "enum": ["article", "fault", "glossary", "note"]},
                "id": {"type": "integer"},
            },
            "required": ["art", "id"],
        },
    },
    {
        "name": "kaeltemittel_daten",
        "description": "Stammdaten eines Kältemittels aus der Datenbank (Sicherheitsgruppe, GWP AR4/AR5, Glide, "
                       "Siedepunkt, kritischer Punkt, Öle, Einsatz, Status, Hinweise).",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "z. B. R290, R448A, R1234ze(E)"}},
            "required": ["code"],
        },
    },
    {
        "name": "saettigung_berechnen",
        "description": "Berechnet Sättigungswerte mit CoolProp. Entweder druck_bar angeben (liefert Siede- und "
                       "Taupunkttemperatur) oder temperatur_c (liefert Siede- und Taudruck in bar(ü) und bar(a)).",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "druck_bar": {"type": "number"},
                "ueberdruck": {"type": "boolean", "description": "true = bar(ü) (Manometer), false = bar(a). Standard true."},
                "temperatur_c": {"type": "number"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "dichtheitskontrolle",
        "description": "CO₂-Äquivalent und Intervall der Dichtheitskontrolle nach F-Gase-VO (EU) 2024/573 "
                       "(vereinfacht) für Kältemittel und Füllmenge.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "fuellmenge_kg": {"type": "number"},
                "gwp_basis": {"type": "string", "enum": ["AR4", "AR5"]},
            },
            "required": ["code", "fuellmenge_kg"],
        },
    },
]


class AssistantError(Exception):
    pass


class WikiTools:
    """Führt die Werkzeug-Aufrufe aus – nur lesend auf die lokale Datenbank."""

    def __init__(self, db: Database):
        self.db = db
        self.links: list[Link] = []

    def _link(self, kind: str, ref_id: int, title: str) -> None:
        if not any(l.kind == kind and l.ref_id == ref_id for l in self.links):
            self.links.append(Link(kind, ref_id, title))

    def run(self, name: str, args: dict[str, Any]) -> str:
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            raise AssistantError(f"Unbekanntes Werkzeug: {name}")
        return json.dumps(fn(**args), ensure_ascii=False)

    def t_wissen_suchen(self, suchtext: str) -> dict:
        hits = self.db.search(str(suchtext), limit=10)
        return {"treffer": [{"art": h.kind, "id": h.ref_id, "titel": h.title,
                             "ausschnitt": h.snippet.replace("«", "").replace("»", "")} for h in hits]}

    def t_eintrag_lesen(self, art: str, id: int) -> dict:  # noqa: A002
        if art == "article":
            a = self.db.article(int(id))
            if not a:
                return {"fehler": "Artikel nicht gefunden"}
            self._link("article", a["id"], a["title"])
            return {"titel": a["title"], "kategorie": self.db.category_path(a["category_id"]),
                    "tags": a["tags"], "text": a["body"]}
        if art == "fault":
            f = self.db.fault(int(id))
            if not f:
                return {"fehler": "Fehlerbild nicht gefunden"}
            self._link("fault", f["id"], f["symptom"])
            return {"symptom": f["symptom"], "bereich": f["area"], "beschreibung": f["description"],
                    "ursachen": [{"ursache": c["cause"], "haeufigkeit": c["likelihood"], "pruefen": c["checks"],
                                  "abhilfe": c["remedy"]} for c in self.db.fault_causes(f["id"])]}
        if art == "glossary":
            g = self.db.glossary_entry(int(id))
            if not g:
                return {"fehler": "Begriff nicht gefunden"}
            self._link("glossary", g["id"], g["term"])
            return {"begriff": g["term"], "erklaerung": g["definition"]}
        if art == "note":
            n = self.db.note(int(id))
            if not n:
                return {"fehler": "Notiz nicht gefunden"}
            self._link("note", n["id"], n["title"])
            return {k: n[k] for k in ("title", "site", "refrigerant", "measurements", "body", "updated")}
        return {"fehler": f"Unbekannte Art: {art}"}

    def _ref(self, code: str):
        r = self.db.refrigerant(code) or next(iter(find_refrigerants(self.db, code)), None)
        if r:
            self._link("refrigerant", r["id"], r["code"])
        return r

    def t_kaeltemittel_daten(self, code: str) -> dict:
        r = self._ref(code)
        if not r:
            return {"fehler": f"Kältemittel {code} ist nicht in der Datenbank."}
        d = {k: r[k] for k in r.keys() if k not in ("id", "coolprop")}
        d["werte_pruefen"] = bool(d.pop("verify"))
        return d

    def t_saettigung_berechnen(self, code: str, druck_bar: float | None = None, ueberdruck: bool = True,
                               temperatur_c: float | None = None) -> dict:
        r = self._ref(code)
        if not r or not r["coolprop"]:
            return {"fehler": f"Für {code} sind keine Stoffdaten hinterlegt."}
        try:
            if druck_bar is not None:
                p_abs = float(druck_bar) + (P_ATM_BAR if ueberdruck else 0)
                return {"kaeltemittel": r["code"], "druck": f"{druck_bar} {'bar(ü)' if ueberdruck else 'bar(a)'}",
                        "siedepunkt_c": round(properties.t_sat(r["coolprop"], p_abs, 0.0), 2),
                        "taupunkt_c": round(properties.t_sat(r["coolprop"], p_abs, 1.0), 2)}
            if temperatur_c is not None:
                pb = properties.p_sat(r["coolprop"], float(temperatur_c), 0.0)
                pd = properties.p_sat(r["coolprop"], float(temperatur_c), 1.0)
                return {"kaeltemittel": r["code"], "temperatur_c": temperatur_c,
                        "siededruck_bar_ue": round(pb - P_ATM_BAR, 3), "taudruck_bar_ue": round(pd - P_ATM_BAR, 3),
                        "siededruck_bar_a": round(pb, 3), "taudruck_bar_a": round(pd, 3)}
        except properties.PropertyError as e:
            return {"fehler": str(e)}
        return {"fehler": "Bitte druck_bar oder temperatur_c angeben."}

    def t_dichtheitskontrolle(self, code: str, fuellmenge_kg: float, gwp_basis: str = "AR4") -> dict:
        r = self._ref(code)
        if not r:
            return {"fehler": f"Kältemittel {code} ist nicht in der Datenbank."}
        gwp = r["gwp_ar5"] if gwp_basis == "AR5" and r["gwp_ar5"] is not None else r["gwp_ar4"]
        if gwp is None:
            return {"fehler": f"Für {r['code']} ist kein GWP hinterlegt."}
        res = calc.leak_check(float(fuellmenge_kg), float(gwp))
        return {"kaeltemittel": r["code"], "gwp": gwp, "gwp_basis": gwp_basis, "co2_aequivalent_t": round(res.co2_eq_t, 3),
                "intervall": res.interval, "intervall_mit_leckage_erkennung": res.interval_with_detection,
                "leckage_erkennung_pflicht": res.detection_required, "hinweis": res.note}


class ClaudeAssistant:
    """Beantwortet Fragen mit Claude; Wissen kommt ausschließlich über die WikiTools."""

    MAX_ROUNDS = 8

    def __init__(self, db: Database, api_key: str | None = None, client: Any = None, app_name: str = "KälteWiki"):
        self.db = db
        self.app_name = app_name
        if client is None:
            try:
                import anthropic
            except ImportError:
                raise AssistantError("Für den KI-Modus fehlt das Paket „anthropic“.") from None
            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.client = client
        self.history: list[dict[str, Any]] = []   # komplette Unterhaltung inkl. Werkzeugaufrufe

    def reset(self) -> None:
        self.history = []

    def answer(self, question: str, db: Database | None = None) -> Answer:
        """db: eigene Verbindung, wenn aus einem Hintergrund-Thread aufgerufen (SQLite ist threadgebunden)."""
        tools = WikiTools(db or self.db)
        messages = self.history + [{"role": "user", "content": question}]
        text_parts: list[str] = []
        for _ in range(self.MAX_ROUNDS):
            response = self.client.beta.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT.format(app=self.app_name),
                tools=TOOLS,
                messages=messages,
                output_config={"effort": "low"},         # Chat: schnelle, knappe Antworten
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",                      # bei Ablehnung automatisch auf Ersatzmodell
            )
            # komplette Antwort zurückgeben (Thinking-/Fallback-Blöcke müssen erhalten bleiben)
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "refusal":
                self.history = messages[:-1]  # abgelehnte Runde nicht weiterführen
                return Answer("Dazu kann ich leider keine Antwort geben. Formulier die Frage gern anders. 🙂",
                              tools.links, "ki")
            text_parts = [b.text for b in response.content if getattr(b, "type", "") == "text" and b.text]
            tool_uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                break
            results = []
            for tu in tool_uses:
                try:
                    content = tools.run(tu.name, dict(tu.input or {}))
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content})
                except Exception as exc:  # Werkzeugfehler an Claude melden, nicht abbrechen
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": str(exc),
                                    "is_error": True})
            messages.append({"role": "user", "content": results})
        else:
            text_parts.append("\n\n*(Ich habe die Recherche nach mehreren Schritten abgebrochen.)*")
        self.history = messages
        text = "\n\n".join(text_parts).strip() or "Ich habe leider keine Antwort erhalten."
        return Answer(text, tools.links, "ki")


def friendly_api_error(exc: Exception) -> str:
    """Übersetzt SDK-Fehler in verständliche Hinweise."""
    try:
        import anthropic
    except ImportError:
        return str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return "Der API-Schlüssel ist ungültig. Bitte unter „Daten & Einstellungen“ prüfen."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "Der API-Schlüssel hat keine Berechtigung für dieses Modell."
    if isinstance(exc, anthropic.RateLimitError):
        return "Zu viele Anfragen – bitte kurz warten und nochmal versuchen."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Keine Verbindung zum KI-Dienst (Internet?)."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Der KI-Dienst meldet einen Fehler ({exc.status_code})."
    return str(exc)
