# Meine Aufgaben

Eine einfache To-do-App in Python mit Tkinter-Oberfläche.

## Starten

```bash
python todo_app.py
```

Unter Windows und macOS ist Tkinter bei Python dabei. Unter Linux ggf. `sudo apt install python3-tk`.

## Funktionen

- Aufgaben hinzufügen (Enter oder „Hinzufügen“), optional mit Fälligkeitsdatum (TT.MM.JJJJ)
- Abhaken per Klick auf ☐, Leertaste oder Knopf „Erledigt / Offen“
- Bearbeiten per Doppelklick, Löschen mit Entf-Taste
- Filter: Alle / Offen / Erledigt, „Erledigte löschen“
- Überfällige Aufgaben in Rot, heute fällige in Orange

Die Aufgaben werden in `aufgaben.json` neben dem Skript gespeichert.

---

# Kältetechnik-Wissensdatenbank (Windows-App)

Im Ordner [`wissensdatenbank/`](wissensdatenbank/) liegt eine Desktop-App für die Kältetechnik: Wissensartikel, Kältemitteldaten, Rechner, Fehlersuche, Glossar, Notizen und Import von eigenem Wissen (PDF, Word, Bilder, Ordner …). Bauen der `.exe`: `wissensdatenbank\build.bat` doppelklicken – Details im [README](wissensdatenbank/README.md).
