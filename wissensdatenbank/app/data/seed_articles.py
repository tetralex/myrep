"""Startartikel (Markdown). Inhalte sind Praxis-Zusammenfassungen –
maßgeblich sind immer Herstellerangaben und Originaltexte der Normen."""

NORM_HINWEIS = ("> **Hinweis:** Kurzüberblick ohne Anspruch auf Vollständigkeit. Maßgeblich ist immer "
                "der aktuelle Originaltext der Norm bzw. Verordnung.")

CATEGORIES = [
    "Grundlagen",
    "Komponenten",
    "Kältemittel & Öle",
    "Wärmepumpen",
    "Regelung & Elektrik",
    "Inbetriebnahme & Wartung",
    "Störungen & Fehlersuche",
    "Normen & Vorschriften",
]

ARTICLES = [
    # ------------------------------------------------------------------ Grundlagen
    ("Grundlagen", "Der Kältekreislauf", "Grundlagen, Kreislauf", """
Der Kaltdampf-Kältekreislauf transportiert Wärme von einem kalten zu einem warmen Ort. Dafür braucht es **vier Hauptkomponenten**:

| Nr. | Komponente | Was passiert? |
|---|---|---|
| 1 → 2 | **Verdichter** | Saugt Dampf an und verdichtet ihn – Druck und Temperatur steigen. |
| 2 → 3 | **Verflüssiger** | Heißer Dampf gibt Wärme ab, wird enthitzt, kondensiert und unterkühlt. |
| 3 → 4 | **Expansionsorgan** | Druck wird abgebaut, ein Teil des Kältemittels verdampft dabei (Flashgas). |
| 4 → 1 | **Verdampfer** | Kältemittel nimmt Wärme auf und verdampft; anschließend wird es überhitzt. |

## Die zwei Druckseiten

- **Hochdruckseite:** Verdichteraustritt → Verflüssiger → Flüssigkeitsleitung → Expansionsventil
- **Niederdruckseite:** nach dem Expansionsventil → Verdampfer → Saugleitung → Verdichter

## Merksätze

- Verdampfen *nimmt* Wärme auf, Kondensieren *gibt* Wärme ab.
- Die Sättigungstemperatur hängt nur vom Druck ab – deshalb kann man über den Druck die Verdampfungs- und Verflüssigungstemperatur bestimmen.
- Der Verdichter darf **nur Dampf** ansaugen – deshalb ist Überhitzung wichtig.

Siehe auch: *Überhitzung und Unterkühlung richtig messen*, *Das log p-h-Diagramm lesen*.
"""),
    ("Grundlagen", "Das log p-h-Diagramm lesen", "Grundlagen, Diagramm, Enthalpie", """
Im **log p-h-Diagramm** ist der Druck (logarithmisch) über der spezifischen Enthalpie *h* in kJ/kg aufgetragen.

## Bereiche

- **Links der Siedelinie:** unterkühlte Flüssigkeit
- **Unter der Glocke (Nassdampfgebiet):** Gemisch aus Flüssigkeit und Dampf, Dampfgehalt x = 0 … 1
- **Rechts der Taulinie:** überhitzter Dampf
- **Spitze der Glocke:** kritischer Punkt

## Der Kreisprozess im Diagramm

1. **1 → 2 Verdichtung** – entlang (ungefähr) einer Isentropen nach oben rechts
2. **2 → 3 Verflüssigung** – waagrecht nach links (konstanter Druck)
3. **3 → 4 Expansion** – senkrecht nach unten (konstante Enthalpie)
4. **4 → 1 Verdampfung** – waagrecht nach rechts

## Was du ablesen kannst

- Spezifische Kälteleistung: *q₀ = h₁ − h₄*
- Spezifische Verdichterarbeit: *w = h₂ − h₁*
- Leistungszahl Kälte: *COP = q₀ / w*
- Wärmeabgabe im Verflüssiger: *q_c = h₂ − h₃*

Tipp: Der Rechner **„Kreisprozess aus Messwerten“** im Werkzeugkasten macht genau diese Auswertung aus deinen Messwerten.
"""),
    ("Grundlagen", "Überhitzung und Unterkühlung richtig messen", "Messen, Überhitzung, Unterkühlung, Praxis", """
## Überhitzung

**Überhitzung = Rohrtemperatur Saugleitung − Taupunkttemperatur beim Saugdruck**

- Messstelle: am Verdampferaustritt (Fühlerposition des Expansionsventils) für die *Verdampferüberhitzung*, am Verdichtereintritt für die *Gesamtüberhitzung*.
- Bei zeotropen Gemischen die **Taupunkttemperatur** (Q = 1) verwenden.
- Richtwert Verdampferüberhitzung: meist **ca. 4–8 K** (Herstellerangaben beachten).

## Unterkühlung

**Unterkühlung = Siedepunkttemperatur beim Hochdruck − Rohrtemperatur Flüssigkeitsleitung**

- Messstelle: am Verflüssigeraustritt bzw. vor dem Expansionsventil.
- Bei zeotropen Gemischen die **Siedepunkttemperatur** (Q = 0) verwenden.
- Richtwert: meist **ca. 3–8 K**.

## Praxistipps

- Rohrfühler gut anlegen und **isolieren**, Rohr vorher säubern.
- Anlage muss im **stabilen Betrieb** laufen (mind. 10–15 Minuten).
- Monteurhilfen zeigen meist **bar(ü)** – für Stoffdaten wird bar(a) benötigt.
- Messwerte und Bedingungen (Umgebung, Last) dokumentieren.

| Überhitzung | Unterkühlung | Häufige Ursache |
|---|---|---|
| hoch | niedrig | Kältemittelmangel |
| niedrig | hoch | Überfüllung |
| hoch | normal/hoch | Expansionsventil zu weit zu, Filter verstopft |
| niedrig | normal | Expansionsventil zu weit offen, Fühler falsch |
"""),
    ("Grundlagen", "Druck: bar(ü) und bar(a)", "Grundlagen, Druck, Einheiten", """
- **bar(a)** – Absolutdruck, bezogen auf das Vakuum (0 bar(a))
- **bar(ü)** bzw. **bar(g)** – Überdruck, bezogen auf den Umgebungsdruck

**bar(a) = bar(ü) + Umgebungsdruck** (Normaldruck ≈ 1,013 bar)

## Warum ist das wichtig?

Dampftafeln und Stoffdaten-Programme arbeiten mit **Absolutdruck**. Die meisten Manometer und digitalen Monteurhilfen zeigen **Überdruck**. Wer das verwechselt, liegt bei der Sättigungstemperatur schnell um mehrere Kelvin daneben – besonders auf der Niederdruckseite.

## Weitere Einheiten

| Einheit | in bar |
|---|---|
| 1 psi | 0,0689 bar |
| 1 MPa | 10 bar |
| 100 kPa | 1 bar |
| 1 mbar | 0,001 bar |

Im Werkzeugkasten kannst du bei jedem Rechner zwischen bar(ü) und bar(a) umschalten.
"""),
    # ------------------------------------------------------------------ Komponenten
    ("Komponenten", "Verdichterbauarten im Überblick", "Verdichter, Komponenten", """
| Bauart | Leistungsbereich (typisch) | Merkmale |
|---|---|---|
| **Hubkolben** | klein bis mittel | robust, gut zu warten, halbhermetisch oder hermetisch |
| **Rollkolben** | klein | Split-Klima, Haushalt, sehr kompakt |
| **Scroll** | klein bis mittel | wenige bewegte Teile, leise, empfindlich bei Flüssigkeit und falscher Drehrichtung |
| **Schraube** | mittel bis groß | Industrie, stufenlose Leistungsregelung (Schieber), Ölabscheider nötig |
| **Turbo** | groß | ölfrei möglich (Magnetlager), Flüssigkeitskühler |

## Bauformen

- **Hermetisch:** Motor und Verdichter verschweißt – nicht reparierbar
- **Halbhermetisch:** verschraubt – reparierbar
- **Offen:** Antrieb außerhalb, Wellenabdichtung nötig (z. B. NH₃)

## Leistungsregelung

Drehzahlregelung (Inverter), Zylinderabschaltung, Digital-Scroll, Schieberregelung, Verbundschaltung.

## Worauf achten?

- Einsatzgrenzen (Verdampfungs-/Verflüssigungstemperatur, Druckgastemperatur) laut Hersteller
- Ölrückführung und Ölstand
- Sauggasüberhitzung: nicht zu niedrig (Flüssigkeit), nicht zu hoch (Druckgastemperatur)
"""),
    ("Komponenten", "Expansionsventile: TEV und EEV", "Expansion, TEV, EEV, Komponenten", """
## Thermostatisches Expansionsventil (TEV)

Regelt die **Verdampferüberhitzung** mechanisch. Kräfte:

- Fühlerdruck (öffnet) gegen Verdampfungsdruck + Federkraft (schließt)
- **Interner Druckausgleich:** für Verdampfer mit geringem Druckverlust
- **Externer Druckausgleich:** bei Verdampfern mit Kältemittelverteiler / höherem Druckverlust – Ausgleichsleitung *nach* dem Fühler anschließen

**Fühlermontage:** an einem waagrechten Saugrohrstück nach dem Verdampfer, guter Kontakt, isolieren. Lage bei größeren Rohren meist zwischen 2 und 4 Uhr bzw. 8 und 10 Uhr (Herstellerangabe beachten) – nicht unten (Öl).

## Elektronisches Expansionsventil (EEV)

- Ansteuerung über Regler mit Drucktransmitter und Temperaturfühler
- Schrittmotor- oder Pulsventile (PWM)
- Vorteile: größerer Regelbereich, niedrigere Überhitzung möglich, gleitender Hochdruck, Energieeinsparung
- Bei Stromausfall: Schließfunktion (Batterie/Kondensator-Modul oder Magnetventil) beachten

## Weitere Expansionsorgane

Kapillarrohr, Festdrossel (Orifice), Hochdruck-Schwimmer, Hochdruckregelventil (R744 transkritisch).
"""),
    ("Komponenten", "Verflüssiger und Verdampfer", "Verflüssiger, Verdampfer, Wärmeübertrager", """
## Verflüssiger

- **Luftgekühlt:** Lamellenrohr oder Mikrokanal – regelmäßig reinigen
- **Wassergekühlt:** Platten-, Rohrbündel- oder Koaxialwärmeübertrager – Wasserqualität, Frostschutz und Durchfluss prüfen
- **Verdunstungsverflüssiger:** Hygiene (Legionellen) beachten

Typische Temperaturdifferenz luftgekühlt: Verflüssigungstemperatur ca. 10–15 K über Lufteintritt (anlagenabhängig).

## Verdampfer

- **Trockenexpansion:** Überhitzung am Austritt, Regelung über TEV/EEV
- **Überflutet:** Abscheider, sehr gute Wärmeübertragung (Industrie, NH₃)
- **Luftkühler:** Lamellenabstand an Temperatur anpassen (Tiefkühlung: größere Abstände wegen Reif)

## Abtauung

Elektrisch, Heißgas, Umluft (ab ca. +2 °C Raumtemperatur) oder Wasser. Abtauende über Temperatur oder Zeit.
"""),
    ("Komponenten", "Filtertrockner, Schauglas und Sammler", "Filtertrockner, Schauglas, Sammler, Komponenten", """
## Filtertrockner

- Bindet Feuchtigkeit, Säuren und Schmutz
- Einbau in der **Flüssigkeitsleitung**, Durchflussrichtung beachten
- **Nach jedem Öffnen des Kreislaufs tauschen**
- Temperaturdifferenz vor/nach Trockner > 1–2 K → zugesetzt
- Nach Verdichterschaden: Säure-Filter in der Saugleitung (temporär)

## Schauglas mit Feuchteindikator

- Grün = trocken, Gelb = feucht (Farben je nach Hersteller)
- Indikator braucht nach Befüllung einige Stunden Betrieb, bis er zuverlässig anzeigt
- Blasen ≠ automatisch Mangel (Anfahren, Teillast, Flashgas durch Druckverlust)

## Kältemittelsammler

- Gleicht Füllmengenschwankungen aus und ermöglicht Pump-down
- Füllmenge für Servicefälle beachten
- Bei Sammler-Anlagen ist die Unterkühlung am Verflüssigeraustritt nur begrenzt aussagekräftig
"""),
    # ------------------------------------------------------------------ Kältemittel & Öle
    ("Kältemittel & Öle", "Sicherheitsgruppen der Kältemittel", "Kältemittel, Sicherheit, EN 378", """
Kältemittel werden nach **Toxizität** und **Brennbarkeit** eingeteilt (EN 378-1 / ISO 817).

| | Keine Flammenausbreitung (1) | Schwer entflammbar (2L) | Entflammbar (2) | Hochentzündlich (3) |
|---|---|---|---|---|
| **A – geringe Toxizität** | A1: R134a, R404A, R744 | A2L: R32, R1234yf, R454B | A2: R152a | A3: R290, R600a |
| **B – höhere Toxizität** | B1 | B2L: R717 | B2 | B3 |

## Was folgt daraus?

- Füllmengengrenzen abhängig von Sicherheitsgruppe, Aufstellungsbereich und Raumvolumen
- Bei brennbaren Kältemitteln: Zündquellen, Lüftung, Gaswarnung, Werkzeug (Ex-geschützt) beachten
- Bei B-Kältemitteln (NH₃): Maschinenraum, Gaswarnanlage, PSA

Details: siehe *EN 378 – Überblick*.
"""),
    ("Kältemittel & Öle", "Kältemittelöle", "Öl, POE, PAG, Kältemittel", """
| Öl | Typische Kältemittel | Hinweise |
|---|---|---|
| **Mineralöl (MO)** | R22 (alt), R290, R600a, R717 | nicht mit HFKW mischbar |
| **Alkylbenzol (AB)** | R22, Übergangsgemische | |
| **PAO** | R717, R290 | synthetisch, nicht hygroskopisch |
| **POE (Polyolester)** | HFKW, HFO, R744 | **stark hygroskopisch**, Standard für HFKW |
| **PVE** | HFKW (u. a. VRF) | hygroskopisch, hydrolysestabil |
| **PAG** | Fahrzeugklima (R134a/R1234yf), R744 | sehr hygroskopisch |

## Praxisregeln

- **Nur die vom Verdichterhersteller freigegebene Ölsorte und Viskosität** verwenden.
- POE/PAG-Gebinde sofort wieder verschließen, kleine Gebinde verwenden.
- Ölwechsel nach Verdichterschaden; Säuretest durchführen.
- Altöl als gefährlichen Abfall entsorgen.
"""),
    ("Kältemittel & Öle", "Zeotrope Gemische und Temperaturgleit", "Glide, Gemische, Befüllen, Kältemittel", """
Zeotrope Gemische (z. B. R407C, R448A, R449A) verdampfen und kondensieren **nicht bei einer festen Temperatur**: Die Temperatur steigt während der Verdampfung an – das nennt man **Temperaturgleit (Glide)**.

## Was heißt das in der Praxis?

- **Immer flüssig befüllen** – sonst ändert sich die Zusammensetzung (Fraktionierung).
- Flüssig in die Saugleitung nur gedrosselt und langsam einspeisen, damit der Verdichter keine Flüssigkeit ansaugt.
- **Überhitzung:** auf **Taupunkt** (Q = 1) beziehen.
- **Unterkühlung:** auf **Siedepunkt** (Q = 0) beziehen.
- Angabe der Verdampfungstemperatur: Mittelwert oder Taupunkt – im Datenblatt nachsehen.
- Nach größerer Leckage bei stark zeotropen Gemischen: Kältemittel komplett tauschen empfohlen.

Die Kältemittel-Datenbank zeigt für Gemische Siede- und Taudruck getrennt an.
"""),
    ("Kältemittel & Öle", "Natürliche Kältemittel: R290, R744, R717", "R290, R744, R717, natürlich, Kältemittel", """
## R290 (Propan) – A3

- Sehr gute thermodynamische Eigenschaften, GWP ≈ 3
- Hochentzündlich: Füllmengengrenzen, Zündquellenfreiheit, Ex-Bereiche
- Werkzeug: Gaswarngerät, funkenfreie Absaugung, Erdung
- Typisch: steckerfertige Gewerbekälte, Wärmepumpen (Monoblock)

## R744 (CO₂) – A1

- Kritischer Punkt bei **31 °C / 73,8 bar** → im Sommer oft **transkritischer** Betrieb mit Gaskühler und Hochdruckregelventil
- Sehr hohe Drücke, auch im Stillstand (Druckentlastung, Stillstandskühlung)
- Tripelpunkt bei −56,6 °C / 5,18 bar(a): beim Befüllen zuerst **dampfförmig** auf über ca. 5,2 bar bringen, sonst Trockeneisbildung
- Typisch: Supermarkt-Verbundanlagen, Warmwasser-Wärmepumpen

## R717 (Ammoniak) – B2L

- Hervorragende Effizienz, GWP 0
- Giftig, stechender Geruch (warnt früh)
- **Kein Kupfer oder Messing** – Stahl/Edelstahl
- Maschinenraum, Gaswarnanlage, Notausrüstung erforderlich
"""),
    # ------------------------------------------------------------------ Wärmepumpen
    ("Wärmepumpen", "Wärmepumpe: Grundlagen, COP und JAZ", "Wärmepumpe, COP, JAZ, Effizienz", """
Eine Wärmepumpe ist eine Kältemaschine, bei der die **Wärme am Verflüssiger** genutzt wird.

## Kennzahlen

- **COP** (Leistungszahl): Heizleistung / elektrische Leistung in einem bestimmten Betriebspunkt, z. B. A2/W35 (Luft 2 °C, Vorlauf 35 °C)
- **SCOP**: saisonale Leistungszahl nach EN 14825
- **JAZ** (Jahresarbeitszahl): gemessene Wärme / gemessener Strom über ein Jahr – die ehrlichste Zahl

## Faustregeln

- Pro Kelvin niedrigere Vorlauftemperatur steigt der COP um grob **2–3 %**.
- Carnot-COP Heizen = T_c / (T_c − T₀) mit Temperaturen in Kelvin – reale Geräte erreichen ca. 40–60 % davon.

## Wärmequellen

Außenluft, Erdreich (Sonden, Kollektoren), Grundwasser, Abwärme.

## Typische Themen in der Praxis

- Abtauung bei Luft/Wasser-Geräten
- Hydraulischer Abgleich und Mindestdurchfluss
- Schallschutz bei Außenaufstellung
- Kältemittel: R290, R32, R454B, R744 (Warmwasser)
"""),
    # ------------------------------------------------------------------ Regelung & Elektrik
    ("Regelung & Elektrik", "Druckschalter und Sicherheitskette", "Druckschalter, Sicherheit, Elektrik", """
## Hochdruck-Sicherheitseinrichtungen

- **Druckwächter (HD):** schaltet ab und selbsttätig wieder ein
- **Druckbegrenzer:** schaltet ab, Entriegelung von Hand (mit Werkzeug)
- **Sicherheitsdruckbegrenzer:** verriegelt, mit Fehlersicherheit (geprüftes Bauteil)
- Die erforderliche Ausführung hängt u. a. von Füllmenge und Bauart ab – siehe EN 378-2.

## Niederdruckschalter

- Schutz vor zu niedrigem Saugdruck, Pump-down-Funktion
- Nicht als Ersatz für einen Frostschutz verwenden

## Sicherheitskette (typisch)

HD-Begrenzer → Motorschutz (Thermistor/Wicklungsschutz) → Öldrucküberwachung → ND-Schalter → Freigabe Regler

## Fehlersuche

- Kette **bei abgeschalteter Spannung** mit Durchgangsprüfer oder unter Spannung mit geeignetem Messgerät Schritt für Schritt durchmessen
- Auslösende Ursache beheben, nicht nur quittieren
- **Sicherheitseinrichtungen niemals überbrücken**
"""),
    # ------------------------------------------------------------------ Inbetriebnahme & Wartung
    ("Inbetriebnahme & Wartung", "Druckprüfung, Dichtheitsprüfung und Evakuieren", "Druckprüfung, Dichtheit, Vakuum, Inbetriebnahme", """
## 1. Festigkeitsprüfung

- Nachweis, dass die Anlage dem Prüfdruck standhält
- Prüfdruck und Verfahren nach EN 378-2 bzw. Herstellerangaben (bitte prüfen: abhängig von PS und Prüfverfahren)
- Mit trockenem **Stickstoff** (nie Sauerstoff oder Druckluft!), Druckminderer verwenden

## 2. Dichtheitsprüfung

- Mit Stickstoff oder Stickstoff/Wasserstoff-Formiergas (95/5) und Lecksuchgerät
- Haltezeit und Temperaturänderung berücksichtigen
- Ergebnis dokumentieren

## 3. Evakuieren

- Vakuumpumpe mit ausreichender Saugleistung, kurze und große Schläuche, Ventilkerne ausbauen
- Vakuummeter direkt an der Anlage (nicht an der Pumpe)
- Zielwert typisch **unter 1 mbar** (100 Pa) bzw. nach Hersteller-/Projektvorgabe
- **Standzeittest:** Pumpe absperren, Druckanstieg beobachten – steigt der Druck weiter, ist Feuchte oder ein Leck vorhanden

## 4. Befüllen

- Zeotrope Gemische **flüssig** befüllen
- Füllmenge mit Waage erfassen und auf Typenschild/Protokoll eintragen
"""),
    ("Inbetriebnahme & Wartung", "Checkliste Inbetriebnahme", "Checkliste, Inbetriebnahme, Dokumentation", """
## Vor dem Einschalten

- [ ] Festigkeits- und Dichtheitsprüfung durchgeführt und dokumentiert
- [ ] Evakuiert, Standzeittest bestanden
- [ ] Kältemittel und Füllmenge laut Planung, Typenschild ausgefüllt
- [ ] Elektrischer Anschluss, Drehfeld, Schutzleiter geprüft
- [ ] Kurbelwannenheizung rechtzeitig eingeschaltet (laut Hersteller, oft mehrere Stunden)
- [ ] Sicherheitseinrichtungen eingestellt und Funktion geprüft

## Im Betrieb

- [ ] Saug- und Hochdruck, Verdampfungs-/Verflüssigungstemperatur
- [ ] Überhitzung und Unterkühlung
- [ ] Druckgastemperatur
- [ ] Stromaufnahme aller Phasen
- [ ] Ölstand im Verdichter
- [ ] Abtauung getestet
- [ ] Regelparameter dokumentiert

## Übergabe

- [ ] Betreiber eingewiesen
- [ ] Anlagendokumentation, Logbuch, Betriebsanleitung übergeben
- [ ] Prüfpflichten (Dichtheitskontrolle) mitgeteilt

Tipp: Messwerte direkt als Notiz im **Baustellen-Log** speichern.
"""),
    ("Inbetriebnahme & Wartung", "Kältemittel rückgewinnen", "Rückgewinnung, Service, F-Gase", """
- Kältemittel **nie** in die Atmosphäre ablassen – Rückgewinnung ist Pflicht.
- Nur zugelassene Rückgewinnungsflaschen verwenden, **maximal ca. 80 % Füllgrad** (Flaschenkennzeichnung/Waage beachten).
- Pro Kältemittelsorte eigene Flasche – keine Vermischung.
- Rückgewinnungsgerät passend zum Kältemittel (Brennbarkeit!) auswählen.
- Flüssig absaugen geht schneller (Push-Pull-Methode bei größeren Mengen).
- Menge erfassen und im Logbuch dokumentieren.
- Verunreinigtes Kältemittel zur Aufbereitung oder Entsorgung abgeben.
"""),
    # ------------------------------------------------------------------ Störungen
    ("Störungen & Fehlersuche", "Systematische Fehlersuche", "Fehlersuche, Diagnose, Praxis", """
## Vorgehen

1. **Fragen:** Was ist passiert? Seit wann? Was wurde verändert?
2. **Schauen:** Vereisung, Ölspuren, Verschmutzung, Lüfter, Schauglas
3. **Messen:** Drücke, Temperaturen, Überhitzung, Unterkühlung, Strom, Spannung
4. **Vergleichen:** mit Sollwerten, Inbetriebnahmeprotokoll und Herstellerdaten
5. **Eingrenzen:** eine Ursache nach der anderen ausschließen
6. **Beheben und kontrollieren**, Ergebnis dokumentieren

## Die wichtigsten Kennwerte

| Messwert | Aussage |
|---|---|
| Überhitzung | Versorgung des Verdampfers |
| Unterkühlung | Füllmenge / Verflüssigerzustand |
| Verflüssigungstemperatur − Lufteintritt | Verflüssigerzustand |
| Raumluft − Verdampfungstemperatur | Verdampferzustand |
| Druckgastemperatur | Verdichterbelastung |

Nutze den **Fehlersuche-Assistenten**, um mögliche Ursachen zu einem Symptom geführt durchzugehen.
"""),
    # ------------------------------------------------------------------ Normen
    ("Normen & Vorschriften", "EN 378 – Überblick", "Normen, EN 378, Sicherheit", NORM_HINWEIS + """

**EN 378 „Kälteanlagen und Wärmepumpen – Sicherheitstechnische und umweltrelevante Anforderungen“** besteht aus vier Teilen:

| Teil | Inhalt |
|---|---|
| **EN 378-1** | Grundlegende Anforderungen, Begriffe, Klassifikationen, Auswahlkriterien (u. a. Füllmengengrenzen) |
| **EN 378-2** | Konstruktion, Herstellung, Prüfung, Kennzeichnung und Dokumentation |
| **EN 378-3** | Aufstellungsort und Schutz von Personen (z. B. Maschinenräume, Gaswarnung) |
| **EN 378-4** | Betrieb, Instandhaltung, Instandsetzung und Rückgewinnung |

## Wichtige Begriffe

- **Sicherheitsgruppe** (A1 … B3) des Kältemittels
- **Zugangsbereich / Aufstellungsbereich** (z. B. allgemein, beaufsichtigt, nur befugte Personen)
- **Aufstellungsklasse** der Anlage (z. B. im Personenbereich, im Maschinenraum, im Freien)
- **Praktischer Grenzwert** und **Toxizitäts-/Brennbarkeitsgrenzwerte** (ATEL/ODL, LFL) als Basis der Füllmengenbegrenzung

Für Geräte nach Produktnormen (z. B. EN 60335-2-40 / -2-89) gelten teilweise eigene Füllmengenregeln.
"""),
    ("Normen & Vorschriften", "F-Gase-Verordnung (EU) 2024/573 – Überblick", "Normen, F-Gase, Verordnung, Dichtheitskontrolle", NORM_HINWEIS + """

Die **Verordnung (EU) 2024/573** über fluorierte Treibhausgase ersetzt die Verordnung (EU) Nr. 517/2014.

## Kernpunkte

- **Phase-down:** schrittweise Verringerung der in Verkehr gebrachten HFKW-Mengen bis zum Ausstieg (2050)
- **Verbote des Inverkehrbringens** für bestimmte neue Geräte abhängig von GWP und Anwendung (Fristen im Anhang IV – bitte aktuellen Stand prüfen)
- **Dichtheitskontrollen** abhängig vom CO₂-Äquivalent der Füllmenge
- **Zertifizierung** von Personal und Unternehmen – erweitert auch auf alternative Kältemittel
- **Aufzeichnungspflichten** (Logbuch) und Kennzeichnung

## Intervalle Dichtheitskontrolle (vereinfacht)

| CO₂-Äquivalent | ohne Leckage-Erkennungssystem | mit Leckage-Erkennungssystem |
|---|---|---|
| ≥ 5 t | alle 12 Monate | alle 24 Monate |
| ≥ 50 t | alle 6 Monate | alle 12 Monate |
| ≥ 500 t | alle 3 Monate | alle 6 Monate (Erkennungssystem Pflicht) |

Hermetisch geschlossene, entsprechend gekennzeichnete Einrichtungen unter 10 t CO₂-Äq. sind ausgenommen.

**CO₂-Äquivalent [t] = Füllmenge [kg] × GWP / 1000** – Rechner im Werkzeugkasten.
"""),
    ("Normen & Vorschriften", "Weitere Regelwerke im Überblick", "Normen, ISO 5149, DGRL, EN 13313", NORM_HINWEIS + """

| Regelwerk | Worum geht's? |
|---|---|
| **ISO 5149** (Teile 1–4) | Internationales Pendant zur EN 378 |
| **Druckgeräterichtlinie 2014/68/EU (DGRL / PED)** | Inverkehrbringen von Druckgeräten und Baugruppen, Kategorien nach Druck × Volumen und Fluidgruppe, Konformitätsbewertung, CE-Kennzeichnung |
| **EN 13313** | Kompetenz des Personals für Kälteanlagen und Wärmepumpen |
| **EN 12900** | Leistungsangaben von Kältemittelverdichtern |
| **EN 14511 / EN 14825** | Prüfung und saisonale Bewertung von Wärmepumpen und Klimageräten |
| **EN 60335-2-40 / -2-89** | Elektrische Sicherheit von Klimageräten/Wärmepumpen bzw. gewerblichen Kühlgeräten (inkl. Füllmengen brennbarer Kältemittel) |
| **Maschinenrichtlinie / Maschinenverordnung (EU) 2023/1230** | Sicherheitsanforderungen an Maschinen |

Nationale Vorschriften (z. B. Arbeitsstätten-, Betriebssicherheits- oder Kälteanlagenverordnungen) zusätzlich beachten.
"""),
]
