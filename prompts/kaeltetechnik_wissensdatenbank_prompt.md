# Prompt: „KälteWiki“ – Wissensdatenbank für die Kältetechnik (Windows-App)

> Diesen kompletten Text in Claude Code (oder einen anderen KI-Coding-Assistenten) kopieren.

---

## Rolle

Du bist ein erfahrener Python-Entwickler und UI-Designer mit Fachwissen in Kälte- und Klimatechnik.
Baue mir eine vollständige, lauffähige Desktop-App für **Windows 10/11**, die am Ende als **einzelne `.exe`** ausgeliefert wird.

## Ziel der App

**„KälteWiki“** ist eine Wissensdatenbank für Kältetechniker – im Büro und auf der Baustelle (Laptop/Tablet).
Sie bündelt Fachwissen, Kältemitteldaten, Rechenhilfen und eigene Notizen an einem Ort und funktioniert **komplett offline**.

## Stil & Tonalität

- **Modern und locker**: klares, aufgeräumtes Design, abgerundete Ecken, viel Weißraum, Icons, sanfte Animationen.
- **Dunkel- und Hellmodus** (umschaltbar, Standard folgt Windows-Einstellung). Akzentfarbe: kühles Eisblau (#3BA7F0) mit Akzent Türkis.
- Texte in der Oberfläche auf **Deutsch**, per Du, kurz und freundlich (z. B. „Was suchst du heute?“, „Nix gefunden – probier’s mal mit einem anderen Begriff 🧊“).
- Trotz lockerem Ton: **Fachinhalte sachlich, präzise und mit Einheiten** (SI, bar(ü)/bar(a) klar gekennzeichnet).
- Touch-freundlich: große Klickflächen, gut lesbar auch mit Handschuhen/auf der Baustelle.

## Technik-Stack (verbindlich)

- **Python 3.12**
- **PySide6 (Qt 6)** für die Oberfläche, Styling über QSS/Theme-Datei
- **SQLite** als lokale Datenbank, Volltextsuche mit **FTS5**
- **CoolProp** für Stoffdaten der Kältemittel (Druck-/Temperatur-Werte, Enthalpien)
- **Markdown** für Artikelinhalte (Rendering in der App, inkl. Tabellen und Bildern)
- **PyInstaller** zum Bauen einer einzelnen `KaelteWiki.exe` mit eigenem Icon
- Projektstruktur sauber trennen: `ui/`, `core/`, `data/`, `calc/`, `assets/`, `tests/`
- Benutzerdaten unter `%APPDATA%\KaelteWiki\` speichern (Datenbank, Einstellungen, Backups)

## Funktionen

### 1. Startseite / Dashboard
- Große Suchleiste mittig („Was suchst du heute?“) mit Live-Vorschlägen
- Kacheln: Zuletzt angesehen, Favoriten, Schnellrechner, „Tipp des Tages“
- Tastenkürzel `Strg+K` öffnet überall die Schnellsuche

### 2. Wissensartikel
- Kategorien (Baumstruktur), z. B.:
  - Grundlagen (Kältekreislauf, log p-h-Diagramm, Überhitzung/Unterkühlung)
  - Komponenten (Verdichter, Verflüssiger, Verdampfer, Expansionsventile, Sammler, Filtertrockner)
  - Kältemittel & Öle
  - Wärmepumpen
  - Regelung & Elektrik
  - Inbetriebnahme, Wartung, Dichtheits- und Druckprüfung
  - Störungen & Fehlersuche
  - Normen & Vorschriften (Überblick: EN 378, F-Gase-Verordnung (EU) 2024/573, ISO 5149, Druckgeräterichtlinie 2014/68/EU, EN 13313) – mit Hinweis „Kurzüberblick, maßgeblich ist immer der Originaltext der Norm“
- Artikel erstellen, bearbeiten, löschen (Markdown-Editor mit Live-Vorschau)
- Tags, Favoriten, Verknüpfungen zwischen Artikeln, Bilder/PDFs anhängen
- Versionsverlauf pro Artikel (letzte Änderungen wiederherstellbar)

### 3. Kältemittel-Datenbank
- Tabelle mit Filter und Suche, mindestens: R290, R600a, R744, R717, R32, R134a, R404A, R407C, R410A, R448A, R449A, R452A, R454B, R513A, R1234yf, R1234ze(E)
- Felder: Bezeichnung, Typ (rein/Gemisch, Glide), Sicherheitsgruppe (A1/A2L/A3/B2L …), GWP (AR4 und AR5/AR6 getrennt ausweisen), ODP, Siedepunkt, kritischer Punkt, typische Öle, Einsatzbereich, Status/Ausstieg laut F-Gase-Verordnung
- Detailansicht mit **Druck-Temperatur-Tabelle** und kleinem Diagramm (Taupunkt/Siedepunkt bei Gemischen getrennt)
- Vergleichsansicht: 2–3 Kältemittel nebeneinander

### 4. Rechner („Werkzeugkasten“)
- **Überhitzung / Unterkühlung**: Druck + Rohrtemperatur eingeben → Ergebnis in K, mit Ampel (zu niedrig/ok/zu hoch)
- **Druck ↔ Sättigungstemperatur** für jedes Kältemittel (bar(ü)/bar(a) umschaltbar)
- **Einheitenumrechner**: bar/psi/kPa, °C/°F/K, kW/BTU/h/TR, m³/h ↔ l/s
- **CO₂-Äquivalent & Prüfpflicht**: Füllmenge (kg) + Kältemittel → t CO₂-Äq. und Intervall der Dichtheitskontrolle nach F-Gase-Verordnung
- **Leistungszahl (COP/EER)** und einfache Kältekreis-Auswertung aus Messwerten
- Alle Rechner speichern ihre letzten Eingaben; Ergebnisse als Notiz übernehmen oder kopieren

### 5. Fehlersuche-Assistent
- Geführte Diagnose: Symptom auswählen (z. B. „Hochdruck zu hoch“, „Verdampfer vereist“, „Verdichter taktet“) → mögliche Ursachen nach Wahrscheinlichkeit → Prüfschritte → Abhilfe
- Inhalte in der Datenbank editierbar, damit eigene Erfahrungen ergänzt werden können

### 6. Glossar
- Fachbegriffe A–Z mit Kurzerklärung, Verlinkung zu Artikeln

### 7. Eigene Notizen & Baustellen-Log
- Schnelle Notizen mit Datum, Anlage/Kunde, Fotos, Messwerten
- Verknüpfbar mit Artikeln und Kältemitteln

### 8. Daten & Einstellungen
- Export/Import der gesamten Datenbank (ZIP mit JSON + Anhängen), Artikel einzeln als PDF exportieren
- Automatisches Backup beim Beenden (letzte 10 behalten)
- Einstellungen: Theme, Schriftgröße, Standard-Druckeinheit, Startseite

## Startinhalte

Befülle die Datenbank beim ersten Start mit sinnvollen **Beispielinhalten**:
- mind. 15 Wissensartikel aus den genannten Kategorien
- alle oben genannten Kältemittel mit Stammdaten
- mind. 10 Fehlerbilder für den Diagnose-Assistenten
- mind. 40 Glossarbegriffe
Kennzeichne Werte, die du nicht sicher belegen kannst, mit „bitte prüfen“, statt Zahlen zu erfinden.

## Qualität

- Sauberer, kommentierter Code, Typ-Hinweise, keine Abstürze bei falschen Eingaben (freundliche Fehlermeldungen)
- Unit-Tests (pytest) für alle Rechner und die Suche
- Schneller Start (< 3 s), Suche liefert Ergebnisse während des Tippens
- App-Icon (Schneeflocke/Kältekreis-Symbol) als `.ico`

## Lieferumfang

1. Vollständiger Quellcode in der beschriebenen Struktur
2. `requirements.txt`
3. `build.bat`, die per Doppelklick eine virtuelle Umgebung anlegt, Abhängigkeiten installiert und mit PyInstaller die `dist\KaelteWiki.exe` baut
4. `README.md` auf Deutsch: Installation, Bauen der `.exe`, Bedienung, wie man Inhalte ergänzt
5. Optional: Inno-Setup-Skript (`installer.iss`) für einen Windows-Installer mit Startmenü-Eintrag

## Vorgehen

Arbeite in Schritten und zeig mir nach jedem Schritt kurz, was fertig ist:
1. Projektgerüst + Datenbankschema
2. Hauptfenster mit Navigation, Theme und Suche
3. Wissensartikel + Editor
4. Kältemittel-Datenbank + Rechner
5. Fehlersuche, Glossar, Notizen
6. Startinhalte, Tests, Build-Skript, README

Wenn etwas unklar ist, triff eine sinnvolle Annahme, schreib sie ins README und mach weiter.
