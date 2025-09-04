#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import Counter
from pathlib import Path
import re
import sys

# ==============================
# FALLBACK de nombres (mínimo; lo ideal es CARGAR un archivo con todos)
# ==============================
FALLBACK_NAMES = [
    "Bulbasaur","Ivysaur","Venusaur","Charmander","Charmeleon","Charizard",
    "Squirtle","Wartortle","Blastoise","Caterpie","Metapod","Butterfree",
    "Weedle","Kakuna","Beedrill","Pidgey","Pidgeotto","Pidgeot",
    "Rattata","Raticate","Spearow","Fearow",
    "Ekans","Arbok","Pikachu","Raichu","Sandshrew","Sandslash",
    "Nidoran♀","Nidorina","Nidoqueen","Nidoran♂","Nidorino","Nidoking",
    "Clefairy","Clefable","Vulpix","Ninetales","Jigglypuff","Wigglytuff",
    "Zubat","Golbat","Oddish","Gloom","Vileplume","Paras","Parasect",
    "Venonat","Venomoth","Diglett","Dugtrio","Meowth","Persian",
    "Psyduck","Golduck","Mankey","Primeape","Growlithe","Arcanine",
    "Poliwag","Poliwhirl","Poliwrath","Abra","Kadabra","Alakazam",
    "Machop","Machoke","Machamp","Bellsprout","Weepinbell","Victreebel",
    "Tentacool","Tentacruel","Geodude","Graveler","Golem","Ponyta","Rapidash",
    "Slowpoke","Slowbro","Magnemite","Magneton","Farfetch’d","Doduo","Dodrio",
    "Seel","Dewgong","Grimer","Muk","Shellder","Cloyster","Gastly","Haunter","Gengar",
    "Onix","Drowzee","Hypno","Krabby","Kingler","Voltorb","Electrode",
    "Exeggcute","Exeggutor","Cubone","Marowak","Hitmonlee","Hitmonchan",
    "Lickitung","Koffing","Weezing","Rhyhorn","Rhydon","Chansey","Tangela",
    "Kangaskhan","Horsea","Seadra","Goldeen","Seaking","Staryu","Starmie",
    "Mr. Mime","Scyther","Jynx","Electabuzz","Magmar","Pinsir","Tauros",
    "Magikarp","Gyarados","Lapras","Ditto","Eevee","Vaporeon","Jolteon","Flareon",
    "Porygon","Omanyte","Omastar","Kabuto","Kabutops","Aerodactyl",
    "Snorlax","Articuno","Zapdos","Moltres","Dratini","Dragonair","Dragonite","Mewtwo","Mew", "PLAGUEKROW", "FAIRY GEM", "RUN AWAY", "POKEMON MOVIE", "TIRTOUGA", "GLOBAL TRADE STATION", "ETERNAL TOWER", "DUSKNOIR", "TRAINERPOINTS", "GOOSEBOARDER", "SPRAY DUCK", "WOOPICE"
]

NORMALIZE_REGEX = re.compile(r"[A-Za-z]")

def normalize_for_length(name: str, letters_only: bool) -> str:
    """Si letters_only=True, contamos solo A-Z (ignora espacios, guiones, símbolos)."""
    if not letters_only:
        return name
    return "".join(NORMALIZE_REGEX.findall(name))

def most_common_length(names: list[str], letters_only: bool) -> tuple[int, int, Counter]:
    if not names:
        return (0, 0, Counter())
    lengths = [len(normalize_for_length(n, letters_only)) for n in names]
    c = Counter(lengths)
    length, count = c.most_common(1)[0]
    return length, count, c

def filter_by_length(names: list[str], wanted_len: int | None, letters_only: bool) -> list[str]:
    if wanted_len is None:
        return names[:]
    out = []
    for n in names:
        ln = len(normalize_for_length(n, letters_only))
        if ln == wanted_len:
            out.append(n)
    return out

def filter_include(names: list[str], letters: set[str], letters_only: bool) -> list[str]:
    if not letters:
        return names
    out = []
    for n in names:
        s = normalize_for_length(n.lower(), letters_only)
        if all(ch in s for ch in letters):
            out.append(n)
    return out

def filter_exclude(names: list[str], letters: set[str], letters_only: bool) -> list[str]:
    if not letters:
        return names
    out = []
    for n in names:
        s = normalize_for_length(n.lower(), letters_only)
        if all(ch not in s for ch in letters):
            out.append(n)
    return out

class PokeGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pokémon Name Filter — al grano 😎")
        self.geometry("900x600")
        self.minsize(800, 520)

        # Datos
        self.base_names: list[str] = FALLBACK_NAMES[:]
        self.filtered: list[str] = self.base_names[:]

        # Estado de filtros
        self.letters_only_var = tk.BooleanVar(value=True)
        self.length_var = tk.StringVar(value="")
        self.include_var = tk.StringVar(value="")
        self.exclude_var = tk.StringVar(value="")

        # UI
        self._build_menu()
        self._build_controls()
        self._build_list()
        self._build_status()

        # Eventos que disparan filtrado
        self.length_var.trace_add("write", lambda *_: self.apply_filters())
        self.include_var.trace_add("write", lambda *_: self.apply_filters())
        self.exclude_var.trace_add("write", lambda *_: self.apply_filters())
        self.letters_only_var.trace_add("write", lambda *_: self.apply_filters())

        # Primera actualización
        self.apply_filters()

    # ---------- UI ----------
    def _build_menu(self):
        m = tk.Menu(self)
        self.config(menu=m)

        file_menu = tk.Menu(m, tearoff=0)
        file_menu.add_command(label="Cargar archivo…", command=self.load_file)
        file_menu.add_command(label="Pegar lista…", command=self.paste_list_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Guardar filtrado…", command=self.save_filtered)
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self.destroy)
        m.add_cascade(label="Archivo", menu=file_menu)

        help_menu = tk.Menu(m, tearoff=0)
        help_menu.add_command(label="Ayuda", command=self.show_help)
        m.add_cascade(label="Ayuda", menu=help_menu)

    def _build_controls(self):
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="x")

        # Longitud
        ttk.Label(frm, text="Longitud exacta:").grid(row=0, column=0, sticky="w")
        self.length_entry = ttk.Entry(frm, width=8, textvariable=self.length_var)
        self.length_entry.grid(row=0, column=1, sticky="w", padx=(4, 12))

        # Letters-only
        self.chk_letters = ttk.Checkbutton(frm, text="Sólo letras (ignora símbolos/espacios)", variable=self.letters_only_var)
        self.chk_letters.grid(row=0, column=2, sticky="w", padx=(0, 12))

        # Incluir
        ttk.Label(frm, text="Incluir letras:").grid(row=1, column=0, sticky="w", pady=(8,0))
        self.include_entry = ttk.Entry(frm, width=18, textvariable=self.include_var)
        self.include_entry.grid(row=1, column=1, sticky="w", padx=(4,12), pady=(8,0))
        ttk.Label(frm, text="(ej: ae)").grid(row=1, column=2, sticky="w", pady=(8,0))

        # Excluir
        ttk.Label(frm, text="Excluir letras:").grid(row=2, column=0, sticky="w", pady=(8,0))
        self.exclude_entry = ttk.Entry(frm, width=18, textvariable=self.exclude_var)
        self.exclude_entry.grid(row=2, column=1, sticky="w", padx=(4,12), pady=(8,0))
        ttk.Label(frm, text="(ej: xyz)").grid(row=2, column=2, sticky="w", pady=(8,0))

        # Botones
        btns = ttk.Frame(frm)
        btns.grid(row=0, column=3, rowspan=3, sticky="e")
        ttk.Button(btns, text="Reset", command=self.reset_filters).grid(row=0, column=0, padx=4, pady=2)
        ttk.Button(btns, text="Copiar selección", command=self.copy_selection).grid(row=1, column=0, padx=4, pady=2)
        ttk.Button(btns, text="Copiar todo (filtrado)", command=self.copy_all).grid(row=2, column=0, padx=4, pady=2)

        for i in range(4):
            frm.grid_columnconfigure(i, weight=1)

    def _build_list(self):
        frm = ttk.Frame(self, padding=(8,0,8,8))
        frm.pack(fill="both", expand=True)

        self.count_label = ttk.Label(frm, text="Resultados: 0")
        self.count_label.pack(anchor="w", pady=(0,6))

        # Listbox + scrollbar
        inner = ttk.Frame(frm)
        inner.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(inner, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)

    def _build_status(self):
        self.status = ttk.Label(self, text="Listo", anchor="w", relief="sunken")
        self.status.pack(fill="x")

    # ---------- Lógica ----------
    def show_help(self):
        messagebox.showinfo(
            "Ayuda rápida",
            "• Cargá un archivo con 1 nombre por línea (inglés)\n"
            "• Longitud: dejá vacío para no filtrar por tamaño\n"
            "• 'Sólo letras': ignora guiones, espacios, etc. al contar\n"
            "• Incluir/Excluir: escribe letras (ae / xyz)\n"
            "• Menú Archivo -> Guardar filtrado para exportar\n"
        )

    def apply_filters(self):
        try:
            wanted_len = self._parse_length(self.length_var.get())
        except ValueError:
            self.status.config(text="Longitud inválida")
            return

        letters_only = self.letters_only_var.get()
        include_set = set(self.include_var.get().strip().lower())
        exclude_set = set(self.exclude_var.get().strip().lower())

        cur = self.base_names[:]
        cur = filter_by_length(cur, wanted_len, letters_only)
        cur = filter_include(cur, include_set, letters_only)
        cur = filter_exclude(cur, exclude_set, letters_only)

        self.filtered = sorted(cur, key=str.lower)
        self._refresh_listbox()
        self._update_stats_display()

    def _parse_length(self, text: str) -> int | None:
        t = text.strip()
        if t == "":
            return None
        if not t.isdigit():
            raise ValueError("not int")
        n = int(t)
        if n <= 0:
            raise ValueError("nonpositive")
        return n

    def _refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for n in self.filtered:
            self.listbox.insert(tk.END, n)
        self.count_label.config(text=f"Resultados: {len(self.filtered)}")

    def _update_stats_display(self):
        letters_only = self.letters_only_var.get()
        if not self.filtered:
            self.status.config(text="Sin resultados")
            return
        length, count, counter = most_common_length(self.filtered, letters_only)
        # Top 5 longitudes
        top5 = ", ".join([f"{l}:{c}" for l,c in counter.most_common(5)])
        self.status.config(text=f"Más común: {length} letras (x{count}) | Top longitudes: {top5}")

    def reset_filters(self):
        self.length_var.set("")
        self.include_var.set("")
        self.exclude_var.set("")
        self.letters_only_var.set(True)
        self.apply_filters()

    def copy_selection(self):
        sel = [self.listbox.get(i) for i in self.listbox.curselection()]
        if not sel:
            messagebox.showinfo("Copiar selección", "No hay selección.")
            return
        self._to_clipboard("\n".join(sel))
        self.status.config(text=f"Copiados {len(sel)} nombres al portapapeles")

    def copy_all(self):
        if not self.filtered:
            messagebox.showinfo("Copiar todo", "No hay resultados.")
            return
        self._to_clipboard("\n".join(self.filtered))
        self.status.config(text=f"Copiados {len(self.filtered)} nombres filtrados")

    def _to_clipboard(self, text: str):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            # ambientes sin clipboard (algunos servidores remotos)
            pass

    def load_file(self):
        path = filedialog.askopenfilename(
            title="Cargar lista de nombres (uno por línea)",
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                names = [ln.strip() for ln in f if ln.strip()]
            if not names:
                messagebox.showwarning("Archivo vacío", "El archivo no contiene nombres.")
                return
            self.base_names = names
            self.status.config(text=f"Cargado: {Path(path).name} ({len(names)} nombres)")
            self.apply_filters()
        except Exception as e:
            messagebox.showerror("Error al cargar", str(e))

    def save_filtered(self):
        if not self.filtered:
            messagebox.showinfo("Guardar", "No hay resultados para guardar.")
            return
        path = filedialog.asksaveasfilename(
            title="Guardar resultados",
            defaultextension=".txt",
            filetypes=[("Texto", "*.txt")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.filtered))
            self.status.config(text=f"Guardado: {Path(path).name} ({len(self.filtered)} nombres)")
        except Exception as e:
            messagebox.showerror("Error al guardar", str(e))

    def paste_list_dialog(self):
        """Ventana para pegar una lista de nombres (uno por línea)."""
        win = tk.Toplevel(self)
        win.title("Pegar lista de nombres")
        win.geometry("600x400")

        txt = tk.Text(win, wrap="word")
        txt.pack(fill="both", expand=True)

        def apply_paste():
            content = txt.get("1.0", "end").strip()
            if not content:
                messagebox.showwarning("Vacío", "Pegá algún contenido.")
                return
            names = [ln.strip() for ln in content.splitlines() if ln.strip()]
            if not names:
                messagebox.showwarning("Vacío", "No se detectaron nombres.")
                return
            self.base_names = names
            self.status.config(text=f"Pegados {len(names)} nombres como base")
            self.apply_filters()
            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(fill="x")
        ttk.Button(btns, text="Usar esta lista", command=apply_paste).pack(side="right", padx=8, pady=6)
        ttk.Button(btns, text="Cerrar", command=win.destroy).pack(side="right", pady=6)

def main():
    app = PokeGUI()
    app.mainloop()

if __name__ == "__main__":
    main()
