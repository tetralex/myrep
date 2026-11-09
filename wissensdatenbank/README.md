# KälteWiki – Wissensdatenbank für die Kältetechnik

Moderne Desktop-App für Windows 10/11, die komplett offline läuft: Fachartikel, Kältemitteldaten, Rechner, Fehlersuche, Glossar, Baustellen-Notizen. Dazu kannst du eigenes Wissen importieren.

> **Name:** „KälteWiki“ ist nur ein Arbeitstitel. Ändern kannst du ihn in `app/config.py` (`APP_NAME`, für den Dateinamen `EXE_NAME`). Fenstertitel, Texte, Build und Installer übernehmen ihn automatisch.

## .exe bauen (Windows)

1. **Python 3.12** von [python.org](https://www.python.org/downloads/) installieren und beim Setup **„Add python.exe to PATH“** anhaken.
2. Den Ordner `wissensdatenbank` auf den PC kopieren.
3. **`build.bat` doppelklicken.** Das Skript
   - legt eine virtuelle Umgebung `.venv` an,
   - installiert alle Pakete,
   - baut mit PyInstaller die Datei **`dist\KaelteWiki.exe`** (eine einzelne Datei, ca. 100–150 MB).
4. Optional: Ist [Inno Setup 6](https://jrsoftware.org/isinfo.php) installiert, baut `build.bat` zusätzlich einen Installer (`dist\installer\Setup_….exe`) mit Startmenü- und Desktop-Verknüpfung.

Zum Testen ohne .exe startest du die App nach dem ersten `build.bat` mit `start.bat`.

### Für Entwickler

```bash
pip install -r requirements-dev.txt
python main.py
python -m pytest
```

## Funktionen

| Bereich | Was geht |
|---|---|
| 🏠 **Start** | Große Suche, Kacheln, zuletzt angesehen, Favoriten, Tipp des Tages |
| 📚 **Wissensartikel** | Kategorien als Baum, Tags, Favoriten, Markdown-Editor mit Live-Vorschau, Bilder, Anhänge, Verknüpfungen, Versionsverlauf, PDF-Export |
| 🧊 **Kältemittel** | 16 Kältemittel mit Sicherheitsgruppe, GWP (AR4/AR5), Glide, Ölen, Status, Druck-Temperatur-Tabelle mit Diagramm (Siede-/Taulinie getrennt), Vergleich von bis zu 3 Kältemitteln |
| 🧮 **Werkzeugkasten** | Überhitzung/Unterkühlung mit Ampel, Druck ↔ Sättigungstemperatur, Kreisprozess aus Messwerten (COP, Enthalpien, Massenstrom), CO₂-Äquivalent und Dichtheitskontrolle, Einheitenumrechner. Die Eingaben bleiben gespeichert, Ergebnisse lassen sich kopieren oder als Notiz ablegen |
| 🩺 **Fehlersuche** | 13 Fehlerbilder: Symptom → Ursachen nach Häufigkeit → Prüfschritte → Abhilfe. Du kannst sie bearbeiten und ergänzen |
| 📖 **Glossar** | 47 Fachbegriffe A–Z, verknüpfbar mit Artikeln |
| 📝 **Notizen** | Baustellen-Log mit Anlage, Kunde, Kältemittel, Messwerten und Fotos. Eine Notiz kannst du als Wissensartikel übernehmen |
| 📥 **Wissen importieren** | siehe unten |
| ⚙️ **Daten & Einstellungen** | Hell/Dunkel/Wie Windows, Schriftgröße, Startseite, Export als Wissenspaket, automatische Sicherung, Wiederherstellung |

**Tastenkürzel:** `Strg+K` Schnellsuche · `Strg+N` neuer Artikel · `Strg+I` importieren · `Strg+S` speichern im Editor

## Neues Wissen importieren

Unter **„Wissen importieren“** (oder Dateien einfach irgendwo ins Fenster ziehen):

| Quelle | Ergebnis |
|---|---|
| **PDF** (.pdf) | Artikel mit dem Text des PDFs, das Original hängt an. Gescannte PDFs ohne Text kommen nur als Anhang rein |
| **Word** (.docx) | Artikel mit Überschriften, Listen und Tabellen, das Original hängt an |
| **Markdown / Text / HTML** | Artikel. Der Titel kommt aus der ersten Überschrift oder dem Dateinamen |
| **Bilder** (.png, .jpg …) | Artikel mit eingebettetem Bild, z. B. Typenschild oder Schaltplan |
| **Ordner** | Alle Dateien darin. Unterordner werden zu Kategorien |
| **CSV fürs Glossar** | Spalten `Begriff;Erklärung` |
| **CSV für Kältemittel** | Spalten wie `code;name;safety;gwp_ar4;gwp_ar5;glide;nbp;t_crit;p_crit;oils;usage;status;coolprop` |
| **Text einfügen** | Text aus E-Mail, Webseite oder Zwischenablage wird zum Artikel |
| **Wissenspaket (.zip)** | Inhalte eines Kollegen werden zusammengeführt, dein eigenes Wissen bleibt erhalten |

Optionen: Zielkategorie, Tags und was passiert, wenn ein Titel schon existiert (neu anlegen / überspringen / aktualisieren). Beim Aktualisieren bleibt die alte Fassung im Versionsverlauf.

**Wissen weitergeben:** Unter „Daten & Einstellungen → Exportieren“ erstellst du ein Wissenspaket mit allem oder nur mit einer Kategorie. Ein Kollege spielt es unter „Wissen importieren → Paket einspielen“ ein.

## Daten

- Gespeichert wird alles unter `%APPDATA%\KaelteWiki\`: `wissen.db` (SQLite), `anhaenge\` und `backups\`.
- Beim Beenden wird automatisch gesichert, die letzten 10 Sicherungen bleiben erhalten.
- Bei einer Deinstallation bleiben deine Daten erhalten.

## Projektstruktur

```
wissensdatenbank/
├── main.py                 Startpunkt
├── app/
│   ├── config.py           App-Name, Version, Pfade  ← Namen hier ändern
│   ├── core/               Datenbank (SQLite + FTS5), Import, Export/Backup
│   ├── calc/               Stoffdaten (CoolProp), Rechner, Einheiten
│   ├── data/               Startinhalte (Artikel, Kältemittel, Fehlerbilder, Glossar)
│   ├── ui/                 Oberfläche (PySide6), Theme, Seiten
│   └── assets/             Icon
├── tests/                  pytest
├── tools/make_icon.py      erzeugt Icon (.png/.ico)
├── app.spec                PyInstaller-Konfiguration
├── build.bat / start.bat   Windows: bauen / starten
└── installer.iss           Inno-Setup-Installer
```

## Annahmen & Hinweise

- **Stoffdaten** kommen aus [CoolProp](http://www.coolprop.org). Gemische wie R448A, R449A, R454B und R513A rechnet CoolProp mit seinen eigenen Gemischmodellen. Die Werte sind gut für die Praxis, ersetzen aber nicht das Datenblatt des Herstellers.
- **GWP-Werte** stehen getrennt nach AR4 und AR5 in der Datenbank. Welche Werte rechtlich gelten, steht im Anhang der F-Gase-VO (EU) 2024/573. Im Rechner kannst du die Basis wählen und den Wert anpassen.
- Werte, die geprüft werden sollten, sind mit ⚠️ markiert („bitte prüfen“).
- Die **Normen-Artikel** sind Kurzüberblicke. Maßgeblich ist immer der Originaltext.
- **Richtwerte** für Überhitzung (3–10 K) und Unterkühlung (2–10 K) sind typische Bereiche. Herstellerangaben haben Vorrang.
- Die Oberfläche nutzt `PySide6-Essentials` (ohne Zusatzmodule), damit die .exe kleiner bleibt. Das Diagramm ist selbst gezeichnet.
