"""Meine Aufgaben – eine einfache To-do-App mit Tkinter.

Start:  python todo_app.py
Die Aufgaben werden in "aufgaben.json" neben dieser Datei gespeichert.
"""

import json
import uuid
from datetime import date, datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

DATEI = Path(__file__).with_name("aufgaben.json")
DATUM_FORMAT = "%d.%m.%Y"  # Eingabe/Anzeige, z. B. 24.12.2026


# ---------- Speichern & Laden ----------

def laden():
    try:
        return json.loads(DATEI.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def speichern(aufgaben):
    DATEI.write_text(json.dumps(aufgaben, ensure_ascii=False, indent=2), encoding="utf-8")


def datum_lesen(text):
    """Wandelt '24.12.2026' in '2026-12-24' um. Leer -> ''. Ungültig -> ValueError."""
    text = text.strip()
    if not text:
        return ""
    return datetime.strptime(text, DATUM_FORMAT).date().isoformat()


def datum_anzeigen(iso):
    return date.fromisoformat(iso).strftime(DATUM_FORMAT) if iso else ""


# ---------- Oberfläche ----------

class TodoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Meine Aufgaben")
        self.geometry("640x520")
        self.minsize(480, 380)

        self.aufgaben = laden()
        self.filter = tk.StringVar(value="alle")

        self._stil()
        self._aufbauen()
        self.aktualisieren()

    def _stil(self):
        stil = ttk.Style(self)
        if "clam" in stil.theme_names():
            stil.theme_use("clam")
        stil.configure("Titel.TLabel", font=("Segoe UI", 20, "bold"))
        stil.configure("Info.TLabel", foreground="#66716b")
        stil.configure("Treeview", rowheight=28, font=("Segoe UI", 11))
        stil.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _aufbauen(self):
        rahmen = ttk.Frame(self, padding=16)
        rahmen.pack(fill="both", expand=True)

        # Kopfzeile
        kopf = ttk.Frame(rahmen)
        kopf.pack(fill="x")
        ttk.Label(kopf, text="Meine Aufgaben", style="Titel.TLabel").pack(side="left")
        self.zaehler = ttk.Label(kopf, style="Info.TLabel")
        self.zaehler.pack(side="right")

        # Eingabe
        eingabe = ttk.Frame(rahmen)
        eingabe.pack(fill="x", pady=(12, 8))
        self.titel_feld = ttk.Entry(eingabe, font=("Segoe UI", 11))
        self.titel_feld.pack(side="left", fill="x", expand=True)
        self.titel_feld.bind("<Return>", lambda e: self.hinzufuegen())
        ttk.Label(eingabe, text="Fällig:").pack(side="left", padx=(8, 4))
        self.datum_feld = ttk.Entry(eingabe, width=11)
        self.datum_feld.pack(side="left")
        self.datum_feld.bind("<Return>", lambda e: self.hinzufuegen())
        ttk.Button(eingabe, text="Hinzufügen", command=self.hinzufuegen).pack(side="left", padx=(8, 0))
        ttk.Label(rahmen, text="Datum optional, Format TT.MM.JJJJ", style="Info.TLabel").pack(anchor="w")

        # Filter
        leiste = ttk.Frame(rahmen)
        leiste.pack(fill="x", pady=(10, 6))
        for wert, text in (("alle", "Alle"), ("offen", "Offen"), ("erledigt", "Erledigt")):
            ttk.Radiobutton(leiste, text=text, value=wert, variable=self.filter,
                            command=self.aktualisieren).pack(side="left", padx=(0, 10))
        ttk.Button(leiste, text="Erledigte löschen", command=self.erledigte_loeschen).pack(side="right")

        # Liste
        liste_rahmen = ttk.Frame(rahmen)
        liste_rahmen.pack(fill="both", expand=True)
        self.liste = ttk.Treeview(liste_rahmen, columns=("status", "titel", "faellig"),
                                  show="headings", selectmode="browse")
        self.liste.heading("status", text="✓")
        self.liste.heading("titel", text="Aufgabe")
        self.liste.heading("faellig", text="Fällig")
        self.liste.column("status", width=40, anchor="center", stretch=False)
        self.liste.column("titel", width=380)
        self.liste.column("faellig", width=110, anchor="center", stretch=False)
        scroll = ttk.Scrollbar(liste_rahmen, orient="vertical", command=self.liste.yview)
        self.liste.configure(yscrollcommand=scroll.set)
        self.liste.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.liste.tag_configure("erledigt", foreground="#9aa39e")
        self.liste.tag_configure("ueberfaellig", foreground="#b4432f")
        self.liste.tag_configure("heute", foreground="#a0661a")

        self.liste.bind("<Double-1>", lambda e: self.bearbeiten())
        self.liste.bind("<space>", lambda e: self.umschalten())
        self.liste.bind("<Delete>", lambda e: self.loeschen())
        self.liste.bind("<Button-1>", self._klick)

        # Aktionen
        aktionen = ttk.Frame(rahmen)
        aktionen.pack(fill="x", pady=(8, 0))
        ttk.Button(aktionen, text="Erledigt / Offen", command=self.umschalten).pack(side="left")
        ttk.Button(aktionen, text="Bearbeiten", command=self.bearbeiten).pack(side="left", padx=8)
        ttk.Button(aktionen, text="Löschen", command=self.loeschen).pack(side="left")
        ttk.Label(aktionen, text="Tipp: Klick auf ✓ hakt ab, Doppelklick bearbeitet",
                  style="Info.TLabel").pack(side="right")

        self.titel_feld.focus()

    # ---------- Anzeige ----------

    def aktualisieren(self):
        self.liste.delete(*self.liste.get_children())
        heute = date.today().isoformat()

        def sortierung(a):
            return (a["erledigt"], a["faellig"] or "9999-99-99", -a["erstellt"])

        for a in sorted(self.aufgaben, key=sortierung):
            f = self.filter.get()
            if (f == "offen" and a["erledigt"]) or (f == "erledigt" and not a["erledigt"]):
                continue
            if a["erledigt"]:
                tag = "erledigt"
            elif a["faellig"] and a["faellig"] < heute:
                tag = "ueberfaellig"
            elif a["faellig"] == heute:
                tag = "heute"
            else:
                tag = ""
            faellig = "Heute" if (a["faellig"] == heute and not a["erledigt"]) else datum_anzeigen(a["faellig"])
            self.liste.insert("", "end", iid=a["id"], tags=(tag,),
                              values=("☑" if a["erledigt"] else "☐", a["titel"], faellig))

        offen = sum(not a["erledigt"] for a in self.aufgaben)
        self.zaehler.config(text=f"{offen} offen · {len(self.aufgaben) - offen} erledigt")

    def _ausgewaehlt(self):
        auswahl = self.liste.selection()
        if not auswahl:
            return None
        return next((a for a in self.aufgaben if a["id"] == auswahl[0]), None)

    def _klick(self, event):
        # Klick in die ✓-Spalte hakt die Aufgabe direkt ab
        if self.liste.identify_column(event.x) == "#1":
            zeile = self.liste.identify_row(event.y)
            if zeile:
                self.liste.selection_set(zeile)
                self.umschalten()
                return "break"

    def _sichern_und_zeigen(self, auswahl_id=None):
        speichern(self.aufgaben)
        self.aktualisieren()
        if auswahl_id and self.liste.exists(auswahl_id):
            self.liste.selection_set(auswahl_id)

    # ---------- Aktionen ----------

    def hinzufuegen(self):
        titel = self.titel_feld.get().strip()
        if not titel:
            self.titel_feld.focus()
            return
        try:
            faellig = datum_lesen(self.datum_feld.get())
        except ValueError:
            messagebox.showerror("Ungültiges Datum",
                                 "Bitte das Datum im Format TT.MM.JJJJ eingeben, z. B. 24.12.2026.")
            self.datum_feld.focus()
            return
        self.aufgaben.append({
            "id": uuid.uuid4().hex,
            "titel": titel,
            "erledigt": False,
            "faellig": faellig,
            "erstellt": datetime.now().timestamp(),
        })
        self.titel_feld.delete(0, "end")
        self.datum_feld.delete(0, "end")
        if self.filter.get() == "erledigt":
            self.filter.set("alle")
        self._sichern_und_zeigen()
        self.titel_feld.focus()

    def umschalten(self):
        a = self._ausgewaehlt()
        if a:
            a["erledigt"] = not a["erledigt"]
            self._sichern_und_zeigen(a["id"])

    def loeschen(self):
        a = self._ausgewaehlt()
        if a and messagebox.askyesno("Löschen", f"„{a['titel']}“ wirklich löschen?"):
            self.aufgaben.remove(a)
            self._sichern_und_zeigen()

    def erledigte_loeschen(self):
        anzahl = sum(a["erledigt"] for a in self.aufgaben)
        if anzahl and messagebox.askyesno("Erledigte löschen", f"{anzahl} erledigte Aufgabe(n) löschen?"):
            self.aufgaben = [a for a in self.aufgaben if not a["erledigt"]]
            self._sichern_und_zeigen()

    def bearbeiten(self):
        a = self._ausgewaehlt()
        if not a:
            return
        fenster = tk.Toplevel(self)
        fenster.title("Aufgabe bearbeiten")
        fenster.transient(self)
        fenster.resizable(False, False)
        inhalt = ttk.Frame(fenster, padding=16)
        inhalt.pack(fill="both", expand=True)

        ttk.Label(inhalt, text="Aufgabe").grid(row=0, column=0, sticky="w")
        titel = ttk.Entry(inhalt, width=40)
        titel.insert(0, a["titel"])
        titel.grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 10))

        ttk.Label(inhalt, text="Fällig (TT.MM.JJJJ, leer = kein Datum)").grid(row=2, column=0, sticky="w")
        datum = ttk.Entry(inhalt, width=14)
        datum.insert(0, datum_anzeigen(a["faellig"]))
        datum.grid(row=3, column=0, sticky="w", pady=(2, 12))

        def ok(event=None):
            neu = titel.get().strip()
            if not neu:
                messagebox.showerror("Leere Aufgabe", "Die Aufgabe braucht einen Text.", parent=fenster)
                return
            try:
                faellig = datum_lesen(datum.get())
            except ValueError:
                messagebox.showerror("Ungültiges Datum",
                                     "Bitte das Datum im Format TT.MM.JJJJ eingeben.", parent=fenster)
                return
            a["titel"], a["faellig"] = neu, faellig
            fenster.destroy()
            self._sichern_und_zeigen(a["id"])

        knoepfe = ttk.Frame(inhalt)
        knoepfe.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(knoepfe, text="Abbrechen", command=fenster.destroy).pack(side="right")
        ttk.Button(knoepfe, text="Speichern", command=ok).pack(side="right", padx=8)

        fenster.bind("<Return>", ok)
        fenster.bind("<Escape>", lambda e: fenster.destroy())
        titel.focus()
        titel.select_range(0, "end")
        fenster.grab_set()


if __name__ == "__main__":
    TodoApp().mainloop()
