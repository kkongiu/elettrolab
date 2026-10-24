import copy
import json
import math
import re
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import report
from .breadboard import Breadboard
from .breadboards import (LayoutError, RAIL_Y, ROWS, derive_nets, generate, hole_xy,
                          parse_hole, place_part, reroute, rotate_part, shift_part,
                          validate_layout, wire_at)
from .circuit import CircuitError
from .db import DB
from .document import Document, slugify
from .layouts import LAYOUTS
from .schematic import Schematic
from .solver import SolveError, check, simulate
from .units import fmt, to_float

DATA = Path(__file__).resolve().parent.parent / "data"
PROJECTS = DATA / "projects"
BG = "#eef1f6"
CARD = "#ffffff"
TEXT = "#1d2433"
MUTED = "#6b7280"
OK = "#137a3f"
FAIL = "#b42318"
WARN = "#b45309"
ACCENT = "#0a5bd3"
SLOW_EXERCISES = {"exp11", "exp11b", "exp11c", "exp11d", "buck"}
SLIDERS = {
    "v": ("lin", 0.0, 24.0),
    "pos": ("lin", 0.0, 1.0),
    "r": ("log", 1.0, 1e6),
    "rtotal": ("log", 10.0, 1e6),
    "c": ("log", 1e-9, 1e-2),
    "l": ("log", 1e-6, 10.0),
}
UNIT = {"v": "V", "r": "Ω", "rtotal": "Ω", "c": "F", "l": "H"}
AMBER = "#f59e0b"

KIND_LABELS = {
    "R": "Resistenze",
    "V": "Alimentazioni",
    "C": "Condensatori",
    "L": "Induttori",
    "LED": "LED",
    "D": "Diodi",
    "SW": "Interruttori",
    "POT": "Potenziometri",
    "RELAY": "Relè",
    "RELAY2": "Relè",
    "GND": "Massa",
    "NPN": "Transistor",
    "PUT": "Transistor",
    "MOS": "Transistor",
    "SPK": "Altoparlanti",
}


class Tooltip:
    """Piccolo tooltip che appare al passaggio del mouse su un widget."""

    def __init__(self, widget, text, delay=450):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 8
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(tip, text=self.text, bg=TEXT, fg="#ffffff",
                 padx=8, pady=3, font=("DejaVu Sans", 9),
                 relief="flat", bd=0).pack()
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class App:
    def __init__(self, root, start=None):
        self.root = root
        self.db = DB(DATA / "components")
        PROJECTS.mkdir(parents=True, exist_ok=True)
        self.ids = sorted(p.stem for p in (DATA / "exercises").glob("*.json"))
        self.results = {}
        self.doc = None
        self.res = None
        self.schem = None
        self.selected = None
        self.selected_wire = None
        self.armed = None
        self.mode = "select"
        self.wire_from = None
        self.cursor_v = None
        self.drag = None
        self.drag_snap = None
        self.dragging = False
        self.pan_last = None
        self.history = []
        self.future = []
        self.dirty = False
        self._loading = False
        self.sim_cache = {}
        self._slide_after = None
        self._bb_drag = None
        self.bb = None
        self.bb_first = tk.BooleanVar(value=True)
        self.bb_tool = "select"
        self.bb_wire_from = None
        self.vline = None
        self.t_anim = 0.0
        self.playing = True
        self.sound_proc = None
        self.frame = 0
        self.last = time.perf_counter()
        self.prop_vars = {}
        self.code_editing = False
        self.show_left = tk.BooleanVar(value=True)
        self.show_right = tk.BooleanVar(value=True)
        self.show_bottom = tk.BooleanVar(value=True)
        root.title("elettrolab - laboratorio di elettronica")
        root.geometry("1280x860")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.configure(bg=BG)
        root.minsize(1020, 720)
        self._build()
        self._check_all()
        self._refresh_projects()
        idx = self.ids.index(start) if start in self.ids else 0
        if self.ids:
            self.ex_list.selection_set(idx)
            self.ex_list.activate(idx)
            self._select_exercise()
        root.after(33, self._tick)

    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED)
        style.configure("Title.TLabel", background=CARD, foreground=TEXT,
                        font=("DejaVu Sans", 16, "bold"))
        style.configure("Status.TLabel", background=CARD, foreground=MUTED,
                        font=("DejaVu Sans", 10, "bold"))
        style.configure("Section.TLabel", background=BG, foreground=MUTED,
                        font=("DejaVu Sans", 9, "bold"))
        style.configure("Treeview", background=CARD, fieldbackground=CARD, rowheight=24,
                        foreground=TEXT, borderwidth=0)
        style.configure("Treeview.Heading", font=("DejaVu Sans", 9, "bold"))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 6), font=("DejaVu Sans", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", CARD)],
                  foreground=[("selected", ACCENT)])
        style.configure("TButton", padding=(8, 4))
        style.configure("Tool.TButton", padding=(5, 2), font=("DejaVu Sans", 12))
        style.configure("ToolOn.TButton", padding=(5, 2), font=("DejaVu Sans", 12),
                        background="#dbe8ff")
        style.map("ToolOn.TButton", background=[("active", "#c7d8f5")])
        style.configure("Accent.TButton", padding=(10, 5),
                        font=("DejaVu Sans", 9, "bold"))
        style.map("Accent.TButton",
                  background=[("!disabled", ACCENT), ("active", "#0847a6")],
                  foreground=[("!disabled", "#ffffff")])

        outer = ttk.Frame(self.root, padding=6)
        outer.pack(fill="both", expand=True)
        self.hpaned = tk.PanedWindow(outer, orient="horizontal", sashwidth=7,
                                     sashrelief="flat", bg="#d9dee8", bd=0,
                                     showhandle=False, opaqueresize=True)
        self.hpaned.pack(fill="both", expand=True)
        left = ttk.Frame(self.hpaned, width=238)
        left.pack_propagate(False)
        main = ttk.Frame(self.hpaned, style="Card.TFrame", padding=12)
        self.hpaned.add(left, minsize=150, width=238, stretch="never")
        self.hpaned.add(main, minsize=420, stretch="always")
        self.left = left

        ttk.Label(left, text="Esercizi", style="TLabel",
                  font=("DejaVu Sans", 11, "bold")).pack(anchor="w")
        self.ex_list = tk.Listbox(left, bg=CARD, fg=TEXT, bd=0, highlightthickness=0,
                                  activestyle="none", selectbackground="#dbe8ff",
                                  selectforeground=TEXT, font=("DejaVu Sans", 10),
                                  height=8, exportselection=False)
        self.ex_list.pack(fill="x")
        self.ex_list.bind("<<ListboxSelect>>", lambda e: self._select_exercise())
        self.summary = ttk.Label(left, text="", style="TLabel", foreground=MUTED)
        self.summary.pack(anchor="w", pady=(2, 6))

        ttk.Label(left, text="Progetti", style="TLabel",
                  font=("DejaVu Sans", 11, "bold")).pack(anchor="w")
        self.proj_list = tk.Listbox(left, bg=CARD, fg=TEXT, bd=0, highlightthickness=0,
                                    activestyle="none", selectbackground="#dbe8ff",
                                    selectforeground=TEXT, font=("DejaVu Sans", 10),
                                    height=4, exportselection=False)
        self.proj_list.pack(fill="x")
        self.proj_list.bind("<<ListboxSelect>>", lambda e: self._open_project())

        row = ttk.Frame(left)
        row.pack(fill="x", pady=(6, 8))
        ttk.Button(row, text="Nuovo", command=self._new, width=7).pack(side="left")
        ttk.Button(row, text="Salva", command=self._save, width=7).pack(side="left", padx=3)
        ttk.Button(row, text="Salva copia", command=self._save_as, width=10).pack(side="left")

        ttk.Label(left, text="Componenti", style="TLabel",
                  font=("DejaVu Sans", 11, "bold")).pack(anchor="w", pady=(0, 2))
        pal = ttk.Frame(left)
        pal.pack(fill="both", expand=True)
        self.pal = ttk.Treeview(pal, show="tree", selectmode="browse", height=12)
        self.pal.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(pal, orient="vertical", command=self.pal.yview)
        sb.pack(side="right", fill="y")
        self.pal.configure(yscrollcommand=sb.set)
        self._fill_palette()
        self.pal.bind("<<TreeviewSelect>>", self._on_palette_select)
        self.hint = ttk.Label(left, text="", style="TLabel", foreground=MUTED,
                              wraplength=220, justify="left")
        self.hint.pack(anchor="w", pady=(8, 0))

        head = ttk.Frame(main, style="Card.TFrame")
        head.pack(fill="x")
        self.title = ttk.Label(head, text="", style="Title.TLabel")
        self.title.pack(anchor="w")
        self.notes = ttk.Label(head, text="", style="Muted.TLabel",
                               wraplength=950, justify="left")
        self.notes.pack(anchor="w", pady=(2, 4))

        bar = ttk.Frame(main, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 4))
        self.mode_btn = self._tool_button(bar, "\u2196", "Seleziona / sposta (Esc)",
                                          lambda: self._set_mode("select"))
        self.wire_btn = self._tool_button(bar, "\u21c4", "Filo: collega due pin",
                                          lambda: self._set_mode("wire"))
        self.delete_btn = self._tool_button(bar, "\u2716",
                                            "Elimina la selezione (Canc/Backspace)",
                                            self._delete_selected)
        self._tool_sep(bar)
        self._tool_button(bar, "\u21b6", "Annulla (Ctrl+Z)", self._undo)
        self._tool_button(bar, "\u21b7", "Ripeti (Ctrl+Y)", self._redo)
        self._tool_button(bar, "\u21bb", "Ruota componente (R)", self._rotate_selected)
        self._tool_sep(bar)
        self._tool_button(bar, "\u27f3", "Simula il circuito", self._after_change,
                          style="Accent.TButton")
        self.sound_btn = self._tool_button(bar, "\u266a", "Ascolta / ferma il suono",
                                           self._play_sound)
        self.status = ttk.Label(bar, text="", style="Status.TLabel")
        self.status.pack(side="left", padx=(14, 0))
        self.viol = ttk.Label(bar, text="", style="Card.TLabel", foreground=FAIL)
        self.viol.pack(side="left", padx=(10, 0))
        self.play = self._tool_button(bar, "\u23f8", "Pausa / riprendi",
                                      self._toggle, side="right")
        self.clock = ttk.Label(bar, text="", style="Muted.TLabel")
        self.clock.pack(side="right", padx=(0, 8))
        self.signal = ttk.Combobox(bar, state="readonly", width=12)
        self.signal.pack(side="right", padx=(0, 6))
        self.signal.bind("<<ComboboxSelected>>", lambda e: self._plot())
        ttk.Label(bar, text="Segnale", style="Muted.TLabel").pack(side="right", padx=(0, 3))

        self.vpaned = tk.PanedWindow(main, orient="vertical", sashwidth=7,
                                     sashrelief="flat", bg="#d9dee8", bd=0,
                                     showhandle=False, opaqueresize=True)
        self.vpaned.pack(fill="both", expand=True, pady=(0, 4))
        upper = ttk.Frame(self.vpaned, style="Card.TFrame")
        self.vpaned.add(upper, minsize=180, stretch="always")
        self.upper = upper
        legend = ttk.Label(upper, text="\u25cf = connessione      linea interrotta = incrocio senza collegamento      "
                                       "scroll = zoom \u00b7 tasto destro = sposta \u00b7 Ctrl+0 = ripristina",
                           style="Muted.TLabel")
        legend.pack(side="bottom", anchor="e")
        self.body = tk.PanedWindow(upper, orient="horizontal", sashwidth=7,
                                   sashrelief="flat", bg="#d9dee8", bd=0,
                                   showhandle=False, opaqueresize=True)
        self.body.pack(fill="both", expand=True)
        self.scv = tk.Canvas(self.body, bg=CARD, height=352, highlightthickness=0)
        side = ttk.Frame(self.body, style="Card.TFrame", width=238)
        side.pack_propagate(False)
        self.body.add(self.scv, minsize=260, stretch="always")
        self.body.add(side, minsize=170, width=238, stretch="never")
        self.side = side
        ttk.Label(side, text="Proprietà", style="Card.TLabel",
                  font=("DejaVu Sans", 10, "bold")).pack(anchor="w")
        self.prop_box = ttk.Frame(side, style="Card.TFrame")
        self.prop_box.pack(fill="x", pady=(2, 4))
        ttk.Label(side, text="Problemi", style="Card.TLabel",
                  font=("DejaVu Sans", 10, "bold")).pack(anchor="w", pady=(4, 0))
        self.problems = tk.Text(side, height=8, width=30, bd=0, bg="#fafbfc",
                                fg=TEXT, font=("DejaVu Sans", 8), wrap="word",
                                padx=6, pady=4, state="disabled")
        self.problems.pack(fill="both", expand=True, pady=(2, 0))

        self.scv.bind("<Button-1>", self._on_press)
        self.scv.bind("<B1-Motion>", self._on_motion)
        self.scv.bind("<ButtonRelease-1>", self._on_release)
        self.scv.bind("<Motion>", self._on_hover)
        self.scv.bind("<Button-3>", self._on_pan_press)
        self.scv.bind("<B3-Motion>", self._on_pan_motion)
        self.scv.bind("<ButtonRelease-3>", self._on_pan_release)
        self.scv.bind("<MouseWheel>", self._on_wheel)
        self.scv.bind("<Button-4>", lambda e: self._on_wheel_step(1.1))
        self.scv.bind("<Button-5>", lambda e: self._on_wheel_step(1 / 1.1))

        self.nb = ttk.Notebook(self.vpaned)
        self.vpaned.add(self.nb, minsize=110, height=250, stretch="always")
        codef = ttk.Frame(self.nb, style="Card.TFrame")
        bbf = ttk.Frame(self.nb, style="Card.TFrame")
        plotf = ttk.Frame(self.nb, style="Card.TFrame")
        dataf = ttk.Frame(self.nb, style="Card.TFrame")
        self.bb_frame = bbf
        self.nb.add(codef, text="Codice")
        self.nb.add(bbf, text="Breadboard")
        self.nb.add(plotf, text="Grafico")
        self.nb.add(dataf, text="Dati")
        bbar = ttk.Frame(bbf, style="Card.TFrame")
        bbar.pack(fill="x")
        ttk.Checkbutton(bbar, text="Breadboard-first", variable=self.bb_first,
                        command=self._toggle_bb_first).pack(side="left", pady=2)
        ttk.Button(bbar, text="Seleziona", width=9,
                   command=lambda: self._set_bb_tool("select")).pack(side="left", padx=(8, 1))
        ttk.Button(bbar, text="Filo", width=6,
                   command=lambda: self._set_bb_tool("wire")).pack(side="left", padx=1)
        ttk.Button(bbar, text="Gomma", width=7,
                   command=lambda: self._set_bb_tool("erase")).pack(side="left", padx=1)
        ttk.Button(bbar, text="Ottimizza", command=self._optimize_board).pack(
            side="left", padx=(8, 0))
        ttk.Label(bbar, text="trascina · R ruota · Canc elimina",
                  style="Muted.TLabel").pack(side="left", padx=8)
        self.bb_canvas = tk.Canvas(bbf, bg=CARD, highlightthickness=0)
        self.bb_canvas.pack(fill="both", expand=True)
        self.bb_canvas.bind("<Button-1>", self._bb_on_press)
        self.bb_canvas.bind("<B1-Motion>", self._bb_on_motion)
        self.bb_canvas.bind("<ButtonRelease-1>", self._bb_on_release)

        cbar = ttk.Frame(codef, style="Card.TFrame")
        cbar.pack(fill="x")
        self.code_view = ttk.Combobox(cbar, state="readonly", width=11,
                                      values=["Circuito", "Layout", "Breadboard"])
        self.code_view.set("Circuito")
        self.code_view.pack(side="left", pady=2)
        self.code_view.bind("<<ComboboxSelected>>", lambda e: self._update_code())
        self.code_btn = ttk.Button(cbar, text="Modifica", width=9,
                                   command=self._toggle_code_edit)
        self.code_btn.pack(side="left", padx=(4, 2))
        ttk.Button(cbar, text="Copia", width=7, command=self._copy_code).pack(side="left")
        ttk.Label(cbar, text="JSON del circuito: è il linguaggio che genera la simulazione",
                  style="Muted.TLabel").pack(side="left", padx=(10, 0))
        cf = ttk.Frame(codef, style="Card.TFrame")
        cf.pack(fill="both", expand=True)
        self.code_text = tk.Text(cf, bd=0, bg="#fbfcfe", fg=TEXT,
                                 font=("DejaVu Sans Mono", 9), wrap="none",
                                 padx=8, pady=6, state="disabled")
        self.code_text.pack(side="left", fill="both", expand=True)
        sy = ttk.Scrollbar(cf, orient="vertical", command=self.code_text.yview)
        sy.pack(side="right", fill="y")
        self.code_text.configure(yscrollcommand=sy.set)
        self.code_text.tag_configure("key", foreground="#0b5cad")
        self.code_text.tag_configure("str", foreground="#1a7f37")
        self.code_text.tag_configure("num", foreground="#9a3412")

        self.fig = Figure(figsize=(7.2, 2.3), dpi=100, facecolor=CARD)
        self.ax = self.fig.add_subplot(111)
        self.plot_canvas = FigureCanvasTkAgg(self.fig, master=plotf)
        self.plot_canvas.get_tk_widget().pack(fill="both", expand=True)
        self.table = ttk.Treeview(dataf, show="headings", height=6)
        self.table.pack(fill="both", expand=True)

        self.root.bind_all("<Control-z>", lambda e: self._key_guard() or self._undo())
        self.root.bind_all("<Control-y>", lambda e: self._key_guard() or self._redo())
        self.root.bind_all("<Control-s>", lambda e: self._key_guard() or self._save())
        self.root.bind_all("<Control-n>", lambda e: self._key_guard() or self._new())
        self.root.bind_all("<Delete>", lambda e: self._key_guard() or self._delete_selected())
        self.root.bind_all("<KP_Delete>", lambda e: self._key_guard() or self._delete_selected())
        self.root.bind_all("<BackSpace>", lambda e: self._key_guard() or self._delete_selected())
        self.root.bind_all("<r>", lambda e: self._key_guard() or self._rotate_selected())
        self.root.bind_all("<Escape>", lambda e: self._escape())
        self.root.bind_all("<Control-0>", lambda e: self._key_guard() or self._reset_view())
        self.root.bind_all("<Control-plus>", lambda e: self._key_guard() or self._zoom(1.2))
        self.root.bind_all("<Control-equal>", lambda e: self._key_guard() or self._zoom(1.2))
        self.root.bind_all("<Control-minus>", lambda e: self._key_guard() or self._zoom(1 / 1.2))
        self._build_menu()

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Nuovo circuito", accelerator="Ctrl+N", command=self._new)
        m.add_command(label="Salva", accelerator="Ctrl+S", command=self._save)
        m.add_command(label="Salva copia\u2026", command=self._save_as)
        m.add_separator()
        m.add_command(label="Esci", command=self._on_close)
        menubar.add_cascade(label="File", menu=m)

        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Annulla", accelerator="Ctrl+Z", command=self._undo)
        m.add_command(label="Ripeti", accelerator="Ctrl+Y", command=self._redo)
        m.add_separator()
        m.add_command(label="Ruota componente", accelerator="R",
                      command=self._rotate_selected)
        m.add_command(label="Elimina", accelerator="Canc",
                      command=self._delete_selected)
        menubar.add_cascade(label="Modifica", menu=m)

        m = tk.Menu(menubar, tearoff=0)
        m.add_checkbutton(label="Barra laterale sinistra", variable=self.show_left,
                          command=self._apply_view)
        m.add_checkbutton(label="Pannello propriet\u00e0", variable=self.show_right,
                          command=self._apply_view)
        m.add_checkbutton(label="Pannello inferiore", variable=self.show_bottom,
                          command=self._apply_view)
        m.add_separator()
        m.add_command(label="Zoom avanti", accelerator="Ctrl++",
                      command=lambda: self._zoom(1.2))
        m.add_command(label="Zoom indietro", accelerator="Ctrl\u2212",
                      command=lambda: self._zoom(1 / 1.2))
        m.add_command(label="Ripristina vista", accelerator="Ctrl+0",
                      command=self._reset_view)
        m.add_separator()
        m.add_command(label="Codice", command=lambda: self.nb.select(0))
        m.add_command(label="Breadboard", command=lambda: self.nb.select(1))
        m.add_command(label="Grafico", command=lambda: self.nb.select(2))
        m.add_command(label="Dati", command=lambda: self.nb.select(3))
        menubar.add_cascade(label="Visualizza", menu=m)

        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Simula", command=self._after_change)
        m.add_command(label="Pausa / Riprendi", command=self._toggle)
        m.add_command(label="Ascolta", command=self._play_sound)
        menubar.add_cascade(label="Simulazione", menu=m)

        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Comandi e scorciatoie", command=self._show_help)
        m.add_command(label="Informazioni", command=self._show_about)
        menubar.add_cascade(label="Aiuto", menu=m)

        self.root.config(menu=menubar)

    def _apply_view(self):
        self._set_pane(self.hpaned, self.left, self.show_left.get(),
                       dict(minsize=150, width=238, stretch="never"))
        self._set_pane(self.body, self.side, self.show_right.get(),
                       dict(minsize=170, width=238, stretch="never"))
        self._set_pane(self.vpaned, self.nb, self.show_bottom.get(),
                       dict(minsize=110, height=250, stretch="always"))

    def _set_pane(self, paned, widget, visible, opts):
        present = str(widget) in [str(p) for p in paned.panes()]
        if visible and not present:
            paned.add(widget, **opts)
        elif not visible and present:
            paned.forget(widget)

    def _show_help(self):
        messagebox.showinfo(
            "Comandi e scorciatoie",
            "Schema:\n"
            "  scroll = zoom, trascina tasto destro = sposta, Ctrl+0 = ripristina vista\n"
            "  clic = seleziona, trascina = sposta componente\n"
            "  R = ruota, Canc/Backspace = elimina (anche un filo selezionato)\n"
            "  modalit\u00e0 Filo: clicca due pin per collegarli\n"
            "  clic su un filo = selezionalo, poi Canc per eliminarlo\n\n"
            "Breadboard:\n"
            "  trascina componenti, R ruota, Canc elimina\n\n"
            "Finestra:\n"
            "  trascina i divisori per ridimensionare sinistra / destra / basso\n"
            "  menu Visualizza per mostrare o nascondere le sezioni\n\n"
            "Scorciatoie: Ctrl+N nuovo, Ctrl+S salva, Ctrl+Z/Ctrl+Y annulla/ripeti",
            parent=self.root)

    def _show_about(self):
        try:
            from . import __version__
        except Exception:
            __version__ = "?"
        messagebox.showinfo(
            "Informazioni",
            f"elettrolab {__version__}\n"
            "Laboratorio di elettronica didattico.\n"
            "Circuiti come dati JSON, motore MNA, breadboard e suono.",
            parent=self.root)

    def _key_guard(self):
        w = self.root.focus_get()
        if w is None:
            return False
        if isinstance(w, (tk.Entry, tk.Text)):
            return True
        return w.winfo_class() in ("Entry", "TEntry", "TCombobox", "Text")

    def _escape(self):
        if self.code_editing:
            return
        self.armed = None
        self.wire_from = None
        self.drag = None
        self.selected_wire = None
        if self.schem is not None:
            self.schem.sel_net = None
        self._set_mode("select")

    def _set_mode(self, mode):
        self.mode = mode
        self.armed = None if mode != "place" else self.armed
        if mode != "wire":
            self.wire_from = None
        on, off = "ToolOn.TButton", "Tool.TButton"
        self.mode_btn.configure(style=on if mode == "select" else off)
        self.wire_btn.configure(style=on if mode == "wire" else off)
        if mode == "wire":
            self._hint("Filo: clicca il primo pin, poi il secondo")
        else:
            self._hint("Seleziona e trascina. R ruota, Canc elimina.")

    def _arm(self, typ):
        spec = self.db.types[typ]
        self.armed = typ
        self.mode = "place"
        self.wire_from = None
        self._hint(f"Clicca sullo schema o sulla breadboard per aggiungere {spec.name}")

    def _hint(self, text):
        self.hint.configure(text=text)

    def _tool_button(self, parent, glyph, tip, command, style="Tool.TButton", side="left"):
        b = ttk.Button(parent, text=glyph, width=3, style=style, command=command)
        b.pack(side=side, padx=1)
        Tooltip(b, tip)
        return b

    def _tool_sep(self, parent):
        ttk.Separator(parent, orient="vertical").pack(side="left", fill="y",
                                                      padx=6, pady=2)

    def _fill_palette(self):
        groups = {}
        for spec in sorted(self.db.types.values(), key=lambda s: (s.kind, s.name)):
            label = KIND_LABELS.get(spec.kind, spec.kind)
            groups.setdefault(label, []).append(spec)
        for label in sorted(groups):
            gid = self.pal.insert("", "end", iid=f"k:{label}", text=label, open=True)
            for spec in groups[label]:
                self.pal.insert(gid, "end", iid=spec.id, text=spec.name)

    def _on_palette_select(self, _event):
        sel = self.pal.selection()
        if not sel:
            return
        iid = sel[0]
        if iid in self.db.types:
            self._arm(iid)

    def _update_summary(self):
        done = [v for v in self.results.values() if v is not None]
        passed = sum(1 for v in done if v)
        total = len(self.ids)
        if len(done) < total:
            self.summary.configure(text=f"{passed}/{total} test superati ({total - len(done)} da eseguire)")
        else:
            self.summary.configure(text=f"{passed}/{total} test superati")

    def _check_all(self):
        previous = dict(self.results)
        self.results = {}
        self.ex_list.delete(0, "end")
        for eid in self.ids:
            if eid in SLOW_EXERCISES:
                ok = previous.get(eid)
                self.results[eid] = ok
                if ok is None:
                    self.ex_list.insert("end", f"   —     {eid}")
                    self.ex_list.itemconfig("end", foreground=MUTED)
                else:
                    self.ex_list.insert("end", f"  {'PASS' if ok else 'FAIL'}   {eid}")
                    self.ex_list.itemconfig("end", foreground=OK if ok else FAIL)
                continue
            try:
                raw = json.loads((DATA / "exercises" / f"{eid}.json").read_text(encoding="utf-8"))
                circ = Document(raw, self.db, layout=LAYOUTS.get(eid)).to_circuit()
                res = simulate(circ)
                check(circ, res)
                ok = res.ok
            except Exception:
                ok = False
            self.results[eid] = ok
            self.ex_list.insert("end", f"  {'PASS' if ok else 'FAIL'}   {eid}")
            self.ex_list.itemconfig("end", foreground=OK if ok else FAIL)
        self._update_summary()

    def _confirm_discard(self):
        if not self.dirty:
            return True
        return messagebox.askyesno("Modifiche non salvate",
                                   "Scartare le modifiche al circuito corrente?",
                                   parent=self.root)

    def _select_exercise(self):
        if getattr(self, "_loading", False):
            return
        sel = self.ex_list.curselection()
        if not sel:
            return
        eid = self.ids[sel[0]]
        if not self._confirm_discard():
            cur = self.doc.meta.get("id") if self.doc else None
            self.ex_list.selection_clear(0, "end")
            if cur in self.ids:
                i = self.ids.index(cur)
                self.ex_list.selection_set(i)
                self.ex_list.activate(i)
            return
        raw = json.loads((DATA / "exercises" / f"{eid}.json").read_text(encoding="utf-8"))
        doc = Document(raw, self.db, layout=LAYOUTS.get(eid), builtin=True)
        self.proj_list.selection_clear(0, "end")
        self.status.configure(text="SIMULAZIONE...", foreground=MUTED)
        self.root.update_idletasks()
        cached = self.sim_cache.get(eid)
        self._load_doc(doc, res=cached)
        if cached is None and self.res is not None:
            self.sim_cache[eid] = self.res
        if self.res is not None:
            self.results[eid] = self.res.ok
            i = self.ids.index(eid)
            self._loading = True
            self.ex_list.delete(i)
            self.ex_list.insert(i, f"  {'PASS' if self.res.ok else 'FAIL'}   {eid}")
            self.ex_list.itemconfig(i, foreground=OK if self.res.ok else FAIL)
            self.ex_list.selection_set(i)
            self._loading = False
        self._update_summary()
        self._hint(f"Esercizio {eid} caricato. Salva una copia per modificarlo.")

    def _load_doc(self, doc, res=None):
        self.doc = doc
        self.schem = None
        self.selected = None
        self.selected_wire = None
        self.wire_from = None
        self.bb_wire_from = None
        self.armed = None
        self.drag = None
        self.mode = "select"
        self.history = []
        self.future = []
        self.dirty = False
        self.t_anim = 0.0
        self.code_editing = False
        self.code_btn.configure(text="Modifica")
        self.code_text.configure(state="disabled")
        self.code_view.configure(state="readonly")
        self.res = res
        self._after_change(simulate=res is None)

    def _new_schem(self):
        old = self.schem
        s = Schematic(self.scv, self.doc, self.res)
        s.sel_net = self.selected_wire
        if old is not None:
            s.zoom = old.zoom
            s.pan_x = old.pan_x
            s.pan_y = old.pan_y
        return s

    def _after_change(self, reset_anim=False, simulate=True, props=True):
        if self.doc is None:
            return
        self.doc.ensure_layout()
        if simulate:
            self._simulate()
        else:
            self.problems_list = self.doc.problems()
        self.schem = self._new_schem()
        if self.doc.board is None or set(self.doc.board.get("parts", {})) != set(self.doc.parts):
            try:
                self.doc.board = generate(self.doc)
            except LayoutError as e:
                self.doc.board = None
                self._hint(str(e))
        elif self.bb_first.get():
            self.doc.nets = derive_nets(self.doc, self.doc.board)
        else:
            reroute(self.doc, self.doc.board)
        if self.doc.board is not None:
            for err in validate_layout(self.doc, self.doc.board):
                self.problems_list.append({**err, "severity": "error"})
        self.bb = Breadboard(self.bb_canvas, self.doc, self.res, self.doc.board)
        self.bb.selected = self.selected
        self._update_sound_button()
        if self.selected not in self.doc.parts:
            self.selected = None
        if self.selected_wire not in self.doc.nets:
            self.selected_wire = None
        if self.schem is not None:
            self.schem.sel_net = self.selected_wire
        if reset_anim:
            self.t_anim = 0.0
        self._update_header()
        self._update_problems()
        self._update_code()
        if props:
            self._update_props()
        self._fill()
        self._plot()

    def _after_board_change(self):
        if self.doc is None or self.doc.board is None:
            return
        if self.bb_first.get():
            self.doc.nets = derive_nets(self.doc, self.doc.board)
        else:
            reroute(self.doc, self.doc.board)
        self.problems_list = self.doc.problems()
        for err in validate_layout(self.doc, self.doc.board):
            self.problems_list.append({**err, "severity": "error"})
        self.bb = Breadboard(self.bb_canvas, self.doc, self.res, self.doc.board)
        self.bb.selected = self.selected
        self._update_sound_button()
        self.dirty = True
        self._update_header()
        self._update_problems()
        self._update_code()
        self._update_props()
        self._fill()
        self._plot()

    def _set_bb_tool(self, tool):
        self.bb_tool = tool
        self.bb_wire_from = None
        if tool == "wire":
            self._hint("Filo: clicca il primo foro, poi il secondo")
        elif tool == "erase":
            self._hint("Gomma: clicca un jumper per rimuoverlo")
        else:
            self._hint("Seleziona: trascina i componenti; R ruota, Canc elimina")

    def _toggle_bb_first(self):
        if self.doc is None or self.doc.board is None:
            return
        self._push_undo()
        if self.bb_first.get():
            self.doc.nets = derive_nets(self.doc, self.doc.board)
            self._after_change()
        else:
            reroute(self.doc, self.doc.board)
            self._after_board_change()

    def _update_sound_button(self):
        if self.sound_proc is not None:
            if self.sound_proc.poll() is None:
                self.sound_proc.terminate()
            self.sound_proc = None
            self.sound_btn.configure(text="\u266a")
        has = bool(self.doc and any(
            self.doc.part(pid) is not None and self.doc.part(pid).kind in ("SPK", "BUZZ")
            for pid in self.doc.parts))
        if has:
            if not self.sound_btn.winfo_manager():
                self.sound_btn.pack(side="left", padx=(8, 0), before=self.status)
        else:
            self.sound_btn.pack_forget()

    def _play_sound(self):
        if self.sound_proc is not None and self.sound_proc.poll() is None:
            self.sound_proc.terminate()
            self.sound_proc = None
            self.sound_btn.configure(text="\u266a")
            self._hint("Suono fermato")
            return
        self.sound_proc = None
        if self.doc is None or self.res is None:
            self._hint("Nessuna simulazione valida da sonorizzare")
            return
        from .audio import AudioError, render
        try:
            info = render(self.doc.to_circuit(), self.res, play_audio=True, loop=True)
        except AudioError as e:
            self._hint(f"Audio: {e}")
            return
        if info.get("proc") is None:
            self._hint(f"WAV pronto: {info['path']}")
            return
        self.sound_proc = info["proc"]
        self.sound_btn.configure(text="\u25a0")
        player = info.get("player") or "player"
        self._hint(f"Ascolta {info['frequency']:.0f} Hz in loop, "
                   f"segnale dell'altoparlante ({player}) - premi Ferma")
        self.root.after(700, self._poll_sound)

    def _poll_sound(self):
        if self.sound_proc is not None and self.sound_proc.poll() is not None:
            self.sound_proc = None
            self.sound_btn.configure(text="\u266a")

    def _on_close(self):
        if self.sound_proc is not None and self.sound_proc.poll() is None:
            self.sound_proc.terminate()
        self.root.destroy()

    def _optimize_board(self):
        if self.doc is None:
            return
        self._push_undo()
        try:
            board = generate(self.doc)
        except LayoutError as e:
            self.history.pop()
            self._hint(str(e))
            return
        self.doc.board = board
        self.selected = None
        self.dirty = True
        self._after_board_change()
        self._hint("Disposizione ottimizzata: massima distanza tra i componenti")

    def _breadboard_active(self):
        return self.nb.select() == str(self.bb_frame)

    def _bb_on_press(self, event):
        if self.doc is None or self.bb is None or self.doc.board is None:
            return
        vx, vy = self.bb.virtual(event.x, event.y)
        if self.armed:
            hole = self.bb.hole_at(vx, vy)
            if hole is None:
                self._hint("Clicca un foro della breadboard")
                return
            typ = self.armed
            self._push_undo()
            pid = self.doc.add_part(typ)
            ok, msg = place_part(self.doc, self.doc.board, pid, hole)
            if not ok:
                self.doc.delete_part(pid)
                self.history.pop()
                self._hint(msg)
                return
            self.selected = pid
            self.armed = None
            self.dirty = True
            self._set_bb_tool("select")
            self._after_change()
            self._hint(f"{pid} aggiunto: collega i pin con Filo")
            return
        if self.bb_tool == "wire":
            if not self.bb_first.get():
                self._hint("Attiva Breadboard-first per usare i fili")
                return
            hole = self.bb.hole_at(vx, vy)
            if hole is None:
                return
            if self.bb_wire_from is None:
                self.bb_wire_from = hole
                self._hint(f"Primo foro {hole}: clicca il secondo")
                return
            if hole == self.bb_wire_from:
                self.bb_wire_from = None
                self._hint("Filo annullato")
                return
            self._push_undo()
            self.doc.board["wires"].append({"net": "fisico",
                                             "points": [self.bb_wire_from, hole]})
            self.bb_wire_from = None
            self.dirty = True
            self._after_change()
            self._hint("Jumper aggiunto; reti ricalcolate")
            return
        if self.bb_tool == "erase":
            if not self.bb_first.get():
                self._hint("Attiva Breadboard-first per usare la gomma")
                return
            idx = wire_at(self.doc.board, vx, vy)
            if idx is None:
                self._hint("Nessun jumper vicino")
                return
            self._push_undo()
            self.doc.board["wires"].pop(idx)
            self.dirty = True
            self._after_change()
            self._hint("Jumper rimosso; reti ricalcolate")
            return
        pid = self.bb.part_at(vx, vy)
        self.selected = pid
        self.bb.selected = pid
        self._update_props()
        self._bb_drag = None
        self.bb_canvas.focus_set()
        if pid is None:
            return
        p = self.doc.part(pid)
        if p is None or p.kind in ("V", "GND"):
            return
        pins = self.doc.board.get("parts", {}).get(pid, {}).get("pins", {})
        if not pins:
            return
        anchor = min(pins, key=lambda pin: (hole_xy(pins[pin])[0] - vx) ** 2 +
                                           (hole_xy(pins[pin])[1] - vy) ** 2)
        self._push_undo()
        self._bb_drag = {"pid": pid, "board": copy.deepcopy(self.doc.board),
                         "anchor": pins[anchor]}

    def _bb_on_motion(self, event):
        if not self._bb_drag or self.doc is None or self.doc.board is None:
            return
        vx, vy = self.bb.virtual(event.x, event.y)
        target = self.bb.hole_at(vx, vy)
        if target is None:
            return
        try:
            t_row, t_col = parse_hole(target)
        except ValueError:
            return
        if t_row in RAIL_Y:
            return
        a_row, a_col = parse_hole(self._bb_drag["anchor"])
        if a_row in RAIL_Y:
            return
        dcol = t_col - a_col
        drow = ROWS.index(t_row) - ROWS.index(a_row)
        if dcol == 0 and drow == 0:
            return
        candidate = copy.deepcopy(self._bb_drag["board"])
        ok, msg = shift_part(self.doc, candidate, self._bb_drag["pid"], dcol, drow)
        if not ok:
            self._hint(msg)
            return
        if self.bb_first.get():
            self.doc.board = candidate
            self.bb = Breadboard(self.bb_canvas, self.doc, self.res, candidate)
            self.bb.selected = self._bb_drag["pid"]
            self._hint(f"{self._bb_drag['pid']} spostato; reti ricalcolate al rilascio")
            return
        reroute(self.doc, candidate)
        errors = validate_layout(self.doc, candidate)
        if errors:
            self._hint(errors[0]["message"])
            return
        self.doc.board = candidate
        self.bb = Breadboard(self.bb_canvas, self.doc, self.res, candidate)
        self.bb.selected = self._bb_drag["pid"]
        self._hint(f"{self._bb_drag['pid']} spostato")

    def _bb_on_release(self, event):
        if not self._bb_drag:
            return
        self._bb_drag = None
        if self.bb_first.get():
            self.doc.nets = derive_nets(self.doc, self.doc.board)
            self._after_change()
        else:
            self._after_board_change()

    def _simulate(self):
        self.problems_list = self.doc.problems()
        self.res = None
        if self.doc.errors():
            return
        try:
            circ = self.doc.to_circuit()
            self.res = simulate(circ)
            check(circ, self.res)
        except (CircuitError, SolveError) as e:
            self.problems_list.append({
                "severity": "error", "code": getattr(e, "code", "error"),
                "message": getattr(e, "message", str(e))})

    def _update_header(self):
        if self.doc is None:
            return
        title = self.doc.meta.get("title") or self.doc.meta.get("id", "circuito")
        star = " *" if self.dirty else ""
        self.title.configure(text=f"{title}{star}")
        self.notes.configure(text=self.doc.meta.get("notes", ""))
        errors = [p for p in self.problems_list if p["severity"] == "error"]
        warnings = [p for p in self.problems_list if p["severity"] == "warning"]
        if errors:
            self.status.configure(text=f"INCOMPLETO  ({len(errors)} errori)",
                                  foreground=FAIL)
        elif self.res is not None and self.res.checks:
            if self.res.ok:
                self.status.configure(text="TEST SUPERATO", foreground=OK)
            else:
                self.status.configure(text="TEST FALLITO", foreground=FAIL)
        elif self.res is not None:
            self.status.configure(text="SIMULAZIONE OK", foreground=OK)
        else:
            self.status.configure(text=f"PRONTO  ({len(warnings)} avvisi)",
                                  foreground=WARN)
        self.viol.configure(text=" | ".join(v["message"] for v in
                                            (self.res.violations if self.res else [])))

    def _update_problems(self):
        items = self.problems_list
        lines = []
        for p in items[:20]:
            mark = "x" if p["severity"] == "error" else "!"
            lines.append(f"{mark} {p['message']}")
        if not lines:
            lines = ["Nessun problema."]
        self.problems.configure(state="normal")
        self.problems.delete("1.0", "end")
        self.problems.insert("1.0", "\n".join(lines))
        self.problems.configure(state="disabled")

    def _update_code(self):
        if self.doc is None or self.code_editing:
            return
        view = self.code_view.get()
        if view == "Breadboard":
            text = json.dumps(self.doc.board or {}, indent=2, ensure_ascii=False)
        else:
            text = self.doc.to_json(layout=(view == "Layout"))
        widget = self.code_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        self._highlight(text)
        widget.configure(state="disabled")
        widget.edit_reset()

    def _highlight(self, text):
        w = self.code_text
        for tag in ("key", "str", "num"):
            w.tag_remove(tag, "1.0", "end")
        for m in re.finditer(r'(?<![\w"])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?', text):
            w.tag_add("num", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in re.finditer(r'"(?:\\.|[^"\\])*"', text):
            after = text[m.end():m.end() + 8]
            tag = "key" if after.lstrip().startswith(":") else "str"
            w.tag_add(tag, f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    def _toggle_code_edit(self):
        if self.code_editing:
            self._apply_code()
            return
        self.code_editing = True
        self.code_text.configure(state="normal")
        self.code_btn.configure(text="Applica")
        self.code_view.configure(state="disabled")
        self._hint("Modifica il JSON e premi Applica. Il layout resta invariato.")

    def _apply_code(self):
        text = self.code_text.get("1.0", "end-1c")
        try:
            data = json.loads(text)
        except Exception as e:
            self._hint(f"JSON non valido: {e}")
            return
        self._push_undo()
        view = self.code_view.get()
        if view == "Breadboard":
            if not isinstance(data, dict):
                self.history.pop()
                self._hint("Il layout breadboard deve essere un oggetto JSON")
                return
            self.doc.board = data
            self.code_editing = False
            self.code_btn.configure(text="Modifica")
            self.code_view.configure(state="readonly")
            self.dirty = True
            self.selected = None
            self._after_board_change()
            return
        if view == "Layout":
            self.doc.layout = self.doc._normalize_layout(data)
            self.doc.ensure_layout()
        else:
            try:
                old_layout = self.doc.to_layout_dict()
                new = Document.from_dict(data, self.db, layout=old_layout,
                                         source=self.doc.source, builtin=self.doc.builtin)
            except Exception as e:
                self.history.pop()
                self._hint(f"Circuito non valido: {e}")
                return
            self.doc = new
        self.code_editing = False
        self.code_btn.configure(text="Modifica")
        self.code_view.configure(state="readonly")
        self.dirty = True
        self.selected = None
        self._after_change(reset_anim=True)

    def _copy_code(self):
        text = self.code_text.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._hint("JSON copiato negli appunti.")

    def _clear_props(self):
        for child in self.prop_box.winfo_children():
            child.destroy()
        self.prop_vars = {}

    def _update_props(self):
        self._clear_props()
        if self.selected_wire:
            name = self.selected_wire
            refs = self.doc.nets.get(name, [])
            ttk.Label(self.prop_box, text=f"Connessione {name}", style="Card.TLabel",
                      font=("DejaVu Sans", 9, "bold")).pack(anchor="w")
            ttk.Label(self.prop_box,
                      text=", ".join(refs) if refs else "(nessun pin)",
                      style="Muted.TLabel", wraplength=210).pack(anchor="w", pady=(2, 0))
            btns = ttk.Frame(self.prop_box, style="Card.TFrame")
            btns.pack(fill="x", pady=(6, 2))
            ttk.Button(btns, text="Elimina", width=8,
                       command=self._delete_selected).pack(side="left")
            return
        pid = self.selected
        if pid is None or pid not in self.doc.parts:
            ttk.Label(self.prop_box, text="Nessun componente selezionato",
                      style="Muted.TLabel", wraplength=210).pack(anchor="w")
            return
        p = self.doc.part(pid)
        if p is None:
            ttk.Label(self.prop_box, text=f"{pid}: tipo sconosciuto",
                      style="Muted.TLabel").pack(anchor="w")
            return
        ttk.Label(self.prop_box, text=f"{pid}   {p.name}", style="Card.TLabel",
                  font=("DejaVu Sans", 9, "bold")).pack(anchor="w")
        for key in p.spec.params:
            val = self.doc.parts[pid].get(key, p.spec.params[key])
            row = ttk.Frame(self.prop_box, style="Card.TFrame")
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=key, style="Muted.TLabel", width=8).pack(side="left")
            if isinstance(val, bool):
                var = tk.BooleanVar(value=val)
                ttk.Checkbutton(row, variable=var).pack(side="left")
            elif key == "mode":
                var = tk.StringVar(value=str(val))
                ttk.Combobox(row, textvariable=var, values=["divider", "rheostat"],
                             width=10, state="readonly").pack(side="left")
            else:
                var = tk.StringVar(value=str(val))
                ttk.Entry(row, textvariable=var, width=11).pack(side="left")
            self.prop_vars[key] = var
            if key in SLIDERS and not isinstance(val, bool):
                try:
                    current = to_float(val)
                except Exception:
                    current = SLIDERS[key][1]
                scale = ttk.Scale(self.prop_box, from_=0.0, to=1.0, orient="horizontal",
                                  value=self._value_to_slider(key, current),
                                  command=lambda x, pid=pid, key=key, var=var:
                                  self._on_slider(pid, key, var, x))
                scale.pack(fill="x", padx=(30, 2), pady=(0, 2))
                scale.bind("<ButtonPress-1>", lambda e: self._push_undo(), add="+")
                scale.bind("<ButtonRelease-1>", lambda e: self._slider_finish(), add="+")
        btns = ttk.Frame(self.prop_box, style="Card.TFrame")
        btns.pack(fill="x", pady=(4, 2))
        ttk.Button(btns, text="Applica", width=8, command=self._apply_props).pack(side="left")
        ttk.Button(btns, text="Ruota", width=6,
                   command=self._rotate_selected).pack(side="left", padx=2)
        ttk.Button(btns, text="Elimina", width=7,
                   command=self._delete_selected).pack(side="left")
        nets = {pin: (self.doc.net_of(pid, pin) or "-") for pin in p.spec.pins}
        ttk.Label(self.prop_box, text="Pin: " + ", ".join(f"{k}={v}" for k, v in nets.items()),
                  style="Muted.TLabel", wraplength=210).pack(anchor="w", pady=(3, 0))

    def _slider_actual(self, key, u):
        mode, lo, hi = SLIDERS[key]
        u = max(0.0, min(1.0, float(u)))
        if mode == "log":
            return 10 ** (math.log10(lo) + (math.log10(hi) - math.log10(lo)) * u)
        return lo + (hi - lo) * u

    def _value_to_slider(self, key, value):
        mode, lo, hi = SLIDERS[key]
        value = max(lo, min(hi, value))
        if mode == "log":
            return (math.log10(value) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        return (value - lo) / (hi - lo)

    def _on_slider(self, pid, key, var, u):
        if pid not in self.doc.parts:
            return
        value = self._slider_actual(key, u)
        var.set(f"{value:.6g}")
        self.doc.set_param(pid, key, value)
        self.dirty = True
        self._hint(f"{pid}.{key} = {fmt(value, UNIT.get(key, ''))}")
        if self._slide_after is not None:
            self.root.after_cancel(self._slide_after)
        self._slide_after = self.root.after(160, self._slider_apply)

    def _slider_apply(self):
        self._slide_after = None
        if self.doc is not None:
            self._after_change(props=False)

    def _slider_finish(self):
        if self._slide_after is not None:
            self.root.after_cancel(self._slide_after)
            self._slide_after = None
        if self.doc is not None:
            self._after_change()

    def _apply_props(self):
        pid = self.selected
        if pid is None or pid not in self.doc.parts:
            return
        p = self.doc.part(pid)
        if p is None:
            return
        numeric = p.spec.numeric_keys()
        values = {}
        for key, var in self.prop_vars.items():
            val = var.get()
            if key in numeric:
                try:
                    to_float(val)
                except Exception:
                    self._hint(f"{pid}.{key}: valore non valido")
                    return
            values[key] = val
        self._push_undo()
        for key, val in values.items():
            self.doc.set_param(pid, key, val)
        self.dirty = True
        self._after_change()

    def _on_hover(self, event):
        if self.mode in ("wire", "place"):
            self.cursor_v = self.schem.virtual(event.x, event.y) if self.schem else None

    def _on_wheel(self, event):
        if self.doc is None or self.schem is None:
            return
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        self.schem.zoom_at(event.x, event.y, factor)

    def _on_wheel_step(self, factor):
        if self.doc is None or self.schem is None:
            return
        self.schem.zoom_at(self.scv.winfo_width() / 2, self.scv.winfo_height() / 2,
                           factor)

    def _on_pan_press(self, event):
        if self.doc is None or self.schem is None:
            return
        self.pan_last = (event.x, event.y)

    def _on_pan_motion(self, event):
        if self.doc is None or self.schem is None or self.pan_last is None:
            return
        dx = event.x - self.pan_last[0]
        dy = event.y - self.pan_last[1]
        self.pan_last = (event.x, event.y)
        self.schem.pan_by(dx, dy)

    def _on_pan_release(self, event):
        self.pan_last = None

    def _zoom(self, factor):
        if self.schem is None:
            return
        self.schem.zoom_at(self.scv.winfo_width() / 2, self.scv.winfo_height() / 2,
                           factor)

    def _reset_view(self):
        if self.schem is not None:
            self.schem.reset_view()
            self._hint("Vista ripristinata.")

    def _on_press(self, event):
        if self.doc is None:
            return
        vx, vy = self.schem.virtual(event.x, event.y)
        self.scv.focus_set()
        if self.armed:
            self._push_undo()
            pid = self.doc.add_part(self.armed, self._snap(vx), self._snap(vy))
            self.selected = pid
            self.armed = None
            self.mode = "select"
            self.dirty = True
            self._after_change()
            self._hint(f"{pid} aggiunto. Trascina per spostarlo, clicca due pin in modalità Filo.")
            return
        if self.mode == "wire":
            pin = self.schem.pin_at(vx, vy)
            if pin is None:
                self.wire_from = None
                return
            if self.wire_from is None:
                self.wire_from = pin
                return
            if self.wire_from == pin:
                self.wire_from = None
                return
            if self.bb_first.get() and self.doc.board:
                h1 = self.doc.board.get("parts", {}).get(self.wire_from[0], {}).get("pins", {}).get(self.wire_from[1])
                h2 = self.doc.board.get("parts", {}).get(pin[0], {}).get("pins", {}).get(pin[1])
                if not h1 or not h2:
                    self._hint("Pin non posizionati sulla breadboard")
                    self.wire_from = None
                    return
                self._push_undo()
                self.doc.board["wires"].append({"net": "fisico", "points": [h1, h2]})
                self.doc.nets = derive_nets(self.doc, self.doc.board)
                self.wire_from = None
                self.dirty = True
                self._after_change()
                self._hint("Jumper aggiunto dallo schema; reti ricalcolate")
                return
            self._push_undo()
            try:
                net = self.doc.connect(*self.wire_from, *pin)
                self._hint(f"Collegati su {net}.")
            except CircuitError as e:
                self.history.pop()
                self._hint(str(e))
            self.wire_from = None
            self.dirty = True
            self._after_change()
            return
        pid = self.schem.part_at(vx, vy)
        if pid is None:
            net = self.schem.wire_at(vx, vy)
            if net:
                self.selected = None
                self.selected_wire = net
                self.drag = None
                self.schem.sel_net = net
                self._update_props()
                self._hint(f"Connessione {net}: premi Canc per eliminarla")
                return
        self.selected_wire = None
        if self.schem is not None:
            self.schem.sel_net = None
        self.selected = pid
        if pid:
            x, y, _ = self.doc.position(pid)
            self.drag = (pid, vx - x, vy - y)
            self.drag_snap = self.doc.snapshot()
            self.dragging = False
        else:
            self.drag = None
        self._update_props()

    def _on_motion(self, event):
        if self.doc is None or self.schem is None:
            return
        vx, vy = self.schem.virtual(event.x, event.y)
        self.cursor_v = (vx, vy)
        if self.mode != "wire":
            self.wire_from = None
        if not self.drag:
            return
        pid, ox, oy = self.drag
        nx, ny = self._snap(vx - ox), self._snap(vy - oy)
        x, y, _ = self.doc.position(pid)
        if (nx, ny) == (x, y):
            return
        self.dragging = True
        self.doc.move(pid, nx, ny)
        self.schem = self._new_schem()
        self._update_code()

    def _on_release(self, event):
        if self.drag and self.dragging:
            self.history.append(self.drag_snap)
            self.future.clear()
            self.dirty = True
            self._after_change()
        self.drag = None
        self.dragging = False

    def _snap(self, v):
        return int(round(v / 10.0) * 10)

    def _push_undo(self):
        if self.doc is None:
            return
        self.history.append(self.doc.snapshot())
        if len(self.history) > 100:
            self.history.pop(0)
        self.future.clear()

    def _undo(self):
        if not self.history or self.doc is None:
            return
        self.future.append(self.doc.snapshot())
        self.doc.restore(self.history.pop())
        self.selected = None
        self.dirty = True
        self._after_change(reset_anim=True)

    def _redo(self):
        if not self.future or self.doc is None:
            return
        self.history.append(self.doc.snapshot())
        self.doc.restore(self.future.pop())
        self.selected = None
        self.dirty = True
        self._after_change(reset_anim=True)

    def _rotate_selected(self):
        if self.selected in self.doc.parts and self._breadboard_active():
            self._rotate_board_selected()
            return
        if self.selected in self.doc.parts:
            self._push_undo()
            self.doc.rotate(self.selected)
            self.dirty = True
            self._after_change()

    def _rotate_board_selected(self):
        if self.doc is None or self.doc.board is None:
            return
        p = self.doc.part(self.selected)
        if p is None or p.kind in ("V", "GND"):
            self._hint("componente non ruotabile sulla breadboard")
            return
        self._push_undo()
        candidate = copy.deepcopy(self.doc.board)
        ok, msg = rotate_part(self.doc, candidate, self.selected)
        if not ok:
            self.history.pop()
            self._hint(msg)
            return
        if self.bb_first.get():
            self.doc.board = candidate
            self.doc.nets = derive_nets(self.doc, self.doc.board)
            self.dirty = True
            self._after_change()
            return
        reroute(self.doc, candidate)
        errors = validate_layout(self.doc, candidate)
        if errors:
            self.history.pop()
            self._hint(errors[0]["message"])
            return
        self.doc.board = candidate
        self._after_board_change()

    def _delete_selected(self):
        if self.selected_wire:
            self._delete_net(self.selected_wire)
            return
        if self.selected in self.doc.parts:
            self._push_undo()
            self.doc.delete_part(self.selected)
            self.selected = None
            self.dirty = True
            self._after_change()

    def _delete_net(self, name):
        if self.doc is None or name not in self.doc.nets:
            return
        self._push_undo()
        if self.bb_first.get() and self.doc.board is not None:
            self.doc.board["wires"] = [w for w in self.doc.board.get("wires", [])
                                       if w.get("net") != name]
            self.doc.nets = derive_nets(self.doc, self.doc.board)
        else:
            self.doc.nets.pop(name, None)
        self.selected_wire = None
        self.selected = None
        self.dirty = True
        self._after_change()
        if name in self.doc.nets:
            self._hint(f"Connessione {name}: ponticelli rimossi, ma resta un collegamento fisico")
        else:
            self._hint(f"Connessione {name} eliminata")

    def _new(self):
        if not self._confirm_discard():
            return
        doc = Document({"id": "nuovo", "title": "Nuovo circuito", "analysis": "dc",
                        "parts": {}, "nets": {}}, self.db,
                       layout={"parts": {}, "gnd_y": 330})
        self.proj_list.selection_clear(0, "end")
        self.ex_list.selection_clear(0, "end")
        self._load_doc(doc)
        self._hint("Nuovo circuito. Aggiungi componenti dalla palette.")

    def _save(self):
        if self.doc is None:
            return
        if self.doc.source and not self.doc.builtin:
            self.doc.save(self.doc.source, self.doc.source.with_suffix(".layout.json"),
                          self.doc.source.with_suffix(".board.json"))
            self.dirty = False
            self._update_header()
            self._refresh_projects()
            return
        self._save_as()

    def _save_as(self):
        if self.doc is None:
            return
        name = simpledialog.askstring("Salva progetto", "Nome del progetto:",
                                      initialvalue=self.doc.meta.get("title", "circuito"),
                                      parent=self.root)
        if not name:
            return
        slug = slugify(name)
        path = PROJECTS / f"{slug}.json"
        layout = PROJECTS / f"{slug}.layout.json"
        board = PROJECTS / f"{slug}.board.json"
        if path.exists() and not messagebox.askyesno(
                "Esiste già", f"{slug}.json esiste. Sovrascrivere?", parent=self.root):
            return
        self.doc.meta["id"] = slug
        self.doc.meta["title"] = name
        self.doc.save(path, layout, board)
        self.dirty = False
        self._refresh_projects(select=slug)
        self._update_header()
        self._hint(f"Salvato in {path}")

    def _refresh_projects(self, select=None):
        self.proj_list.delete(0, "end")
        names = sorted(p.stem for p in PROJECTS.glob("*.json")
                       if not p.name.endswith((".layout.json", ".board.json")))
        for name in names:
            self.proj_list.insert("end", name)
        if select in names:
            i = names.index(select)
            self.proj_list.selection_set(i)
            self.proj_list.activate(i)

    def _open_project(self):
        sel = self.proj_list.curselection()
        if not sel:
            return
        if not self._confirm_discard():
            self.proj_list.selection_clear(0, "end")
            return
        name = self.proj_list.get(sel[0])
        path = PROJECTS / f"{name}.json"
        layout = PROJECTS / f"{name}.layout.json"
        board = PROJECTS / f"{name}.board.json"
        try:
            doc = Document.from_file(path, layout, self.db, board_path=board)
        except Exception as e:
            self._hint(f"Errore apertura: {e}")
            return
        self.ex_list.selection_clear(0, "end")
        self._load_doc(doc)
        self._hint(f"Progetto {name} aperto.")

    def _fill(self):
        for item in self.table.get_children():
            self.table.delete(item)
        r = self.res
        if r is None:
            self.table["columns"] = ("msg",)
            self.table.heading("msg", text="Nessun risultato")
            self.table.column("msg", width=300)
            self.signal.configure(values=[], state="disabled")
            self.signal.set("")
            return
        if r.analysis == "dc":
            self.table["columns"] = ("pid", "corrente", "tensione", "potenza")
            for col, txt, w in (("pid", "Componente", 200), ("corrente", "Corrente", 110),
                                ("tensione", "Tensione", 110), ("potenza", "Potenza", 110)):
                self.table.heading(col, text=txt)
                self.table.column(col, width=w, anchor="center")
            for pid, p in self.doc.parts.items():
                part = self.doc.part(pid)
                if part is None:
                    continue
                self.table.insert("", "end", values=(
                    f"{pid} {part.name}", fmt(r.currents.get(pid, 0.0), "A"),
                    fmt(report.part_voltage(self.doc, r, pid), "V"),
                    fmt(r.power.get(pid, 0.0), "W")))
            self.signal.configure(values=[], state="disabled")
            self.signal.set("")
        else:
            self.table["columns"] = ("sig", "min", "max", "fine")
            for col, txt, w in (("sig", "Segnale", 120), ("min", "min", 110),
                                ("max", "max", 110), ("fine", "finale", 110)):
                self.table.heading(col, text=txt)
                self.table.column(col, width=w, anchor="center")
            for sig, arr in r.waves.items():
                self.table.insert("", "end", values=(
                    sig, fmt(float(arr.min()), "", 4), fmt(float(arr.max()), "", 4),
                    fmt(float(arr[-1]), "", 4)))
            sigs = list(r.waves)
            self.signal.configure(values=sigs, state="readonly")
            if not self.signal.get() or self.signal.get() not in sigs:
                self.signal.set(self._best_signal())

    def _best_signal(self):
        if self.res is None:
            return ""
        best, rng = None, -1.0
        for s, arr in self.res.waves.items():
            if not s.startswith("V("):
                continue
            d = float(arr.max() - arr.min())
            if d > rng:
                best, rng = s, d
        return best or next(iter(self.res.waves), "")

    def _plot(self):
        ax = self.ax
        ax.clear()
        ax.set_facecolor(CARD)
        for spine in ax.spines.values():
            spine.set_color("#d9dee8")
        ax.tick_params(colors=MUTED, labelsize=8)
        ax.grid(True, color="#e6e9f0", linewidth=0.8)
        ax.set_axisbelow(True)
        self.vline = None
        r = self.res
        if r is None:
            ax.set_title("Nessun risultato: completa o correggi il circuito",
                         color=MUTED, fontsize=10, loc="left")
            ax.set_xticks([])
            ax.set_yticks([])
            self.fig.tight_layout()
            self.plot_canvas.draw_idle()
            return
        if r.analysis == "dc":
            names = list(r.nodes)
            vals = [r.nodes[n] for n in names]
            colors = ["#9ec5fe" if abs(v) < 1e-9 else ACCENT for v in vals]
            bars = ax.bar(range(len(names)), vals, color=colors, width=0.55)
            ax.set_xticks(range(len(names)))
            ax.set_xticklabels(names)
            ax.set_ylabel("tensione (V)", color=MUTED)
            ax.set_title("Tensioni di nodo", color=TEXT, fontsize=10, loc="left")
            for bar, v in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width() / 2,
                        v + (0.15 if v >= 0 else -0.15), fmt(v, "V"),
                        ha="center", va="bottom" if v >= 0 else "top",
                        fontsize=8, color=TEXT)
            if vals:
                lo, hi = min(0, min(vals)), max(0, max(vals))
                pad = max(0.5, (hi - lo) * 0.18)
                ax.set_ylim(lo - pad, hi + pad)
        else:
            sig = self.signal.get() or self._best_signal()
            if sig in r.waves:
                t = r.time
                y = r.waves[sig]
                ax.plot(t, y, color=ACCENT, linewidth=1.3)
                ax.fill_between(t, y, color=ACCENT, alpha=0.10)
                ax.set_xlabel("tempo (s)", color=MUTED)
                ax.set_ylabel(sig, color=MUTED)
                ax.set_title(f"{sig} nel tempo", color=TEXT, fontsize=10, loc="left")
                self.vline = ax.axvline(self.t_anim, color="#94a3b8",
                                        linewidth=0.9, linestyle=":")
        self.fig.tight_layout()
        self.plot_canvas.draw_idle()

    def _toggle(self):
        self.playing = not self.playing
        self.play.configure(text="\u23f8" if self.playing else "\u25b6")

    def _draw_overlay(self):
        if self.schem is None or self.doc is None:
            return
        s = self.schem
        if self.selected in self.doc.parts:
            x0, y0, x1, y1 = s.part_bbox(self.selected)
            pts = [s.T(x0, y0), s.T(x1, y1)]
            s.c.create_rectangle(pts[0][0], pts[0][1], pts[1][0], pts[1][1],
                                 outline=ACCENT, width=1.2, dash=(4, 3))
        if self.mode == "wire":
            for pid in self.doc.parts:
                for pin in self.doc.pins(pid):
                    px, py = s.pin_position(pid, pin)
                    X, Y = s.T(px, py)
                    r = 3.0 * s.s
                    s.c.create_oval(X - r, Y - r, X + r, Y + r,
                                    outline=ACCENT, fill="")
            if self.wire_from and self.cursor_v:
                p = s.pin_position(*self.wire_from)
                a = s.T(*p)
                b = s.T(*self.cursor_v)
                s.c.create_line(a[0], a[1], b[0], b[1], fill=AMBER,
                                width=1.4, dash=(4, 3))
                X, Y = a
                r = 4.0 * s.s
                s.c.create_oval(X - r, Y - r, X + r, Y + r, fill=AMBER,
                                outline="")

    def _tick(self):
        now = time.perf_counter()
        d = min(0.1, now - self.last)
        self.last = now
        if self.doc is not None and self.schem is not None:
            t = None
            if self.res is not None and self.res.time is not None:
                if self.playing:
                    span = max(3.0, min(8.0, float(self.res.time[-1])))
                    self.t_anim += d * (float(self.res.time[-1]) / span)
                    if self.t_anim > float(self.res.time[-1]):
                        self.t_anim = 0.0
                t = self.t_anim
                self.clock.configure(text=f"t = {self.t_anim:.2f} s")
            else:
                self.clock.configure(text="DC" if self.res is not None else "")
            self.schem.draw(t, d if self.playing else 0.0, self.playing)
            if self.bb is not None and self.nb.select() == str(self.bb_frame):
                self.bb.draw(t, d if self.playing else 0.0, self.playing)
            self._draw_overlay()
            self.frame += 1
            if t is not None and self.vline is not None and self.frame % 4 == 0:
                self.vline.set_xdata([t, t])
                self.plot_canvas.draw_idle()
        self.root.after(33, self._tick)


def main(eid=None):
    root = tk.Tk()
    App(root, eid)
    root.mainloop()


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)
