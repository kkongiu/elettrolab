import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import report
from .circuit import from_dict
from .db import DB
from .layouts import LAYOUTS
from .schematic import Schematic
from .solver import check, simulate
from .units import fmt

DATA = Path(__file__).resolve().parent.parent / "data"
BG = "#eef1f6"
CARD = "#ffffff"
TEXT = "#1d2433"
MUTED = "#6b7280"
OK = "#137a3f"
FAIL = "#b42318"
ACCENT = "#0a5bd3"


class App:
    def __init__(self, root, start=None):
        self.root = root
        self.db = DB(DATA / "components")
        self.ids = sorted(p.stem for p in (DATA / "exercises").glob("*.json"))
        self.results = {}
        self.circ = None
        self.res = None
        self.schem = None
        self.vline = None
        self.t_anim = 0.0
        self.playing = True
        self.frame = 0
        self.last = time.perf_counter()
        root.title("elettrolab - laboratorio di elettronica")
        root.geometry("1180x830")
        root.configure(bg=BG)
        root.minsize(980, 700)
        self._build()
        self._check_all()
        idx = self.ids.index(start) if start in self.ids else 0
        self.list.selection_clear(0, "end")
        self.list.selection_set(idx)
        self.list.activate(idx)
        self._on_select()
        self.root.after(33, self._tick)

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
                        font=("DejaVu Sans", 15, "bold"))
        style.configure("Status.TLabel", background=CARD, foreground=MUTED,
                        font=("DejaVu Sans", 11, "bold"))
        style.configure("Treeview", background=CARD, fieldbackground=CARD, rowheight=23)
        style.configure("Treeview.Heading", font=("DejaVu Sans", 9, "bold"))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(12, 5))

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        left = ttk.Frame(outer, width=230)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        ttk.Label(left, text="Esercizi", style="TLabel",
                  font=("DejaVu Sans", 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.list = tk.Listbox(left, bg=CARD, fg=TEXT, bd=0, highlightthickness=0,
                               activestyle="none", selectbackground="#dbe8ff",
                               selectforeground=TEXT, font=("DejaVu Sans", 11))
        self.list.pack(fill="both", expand=True)
        self.list.bind("<<ListboxSelect>>", self._on_select)
        self.summary = ttk.Label(left, text="", style="TLabel", foreground=MUTED)
        self.summary.pack(anchor="w", pady=(8, 4))
        ttk.Button(left, text="Riesegui i controlli",
                   command=self._check_all).pack(fill="x")

        right = ttk.Frame(outer, style="Card.TFrame", padding=14)
        right.pack(side="left", fill="both", expand=True)

        head = ttk.Frame(right, style="Card.TFrame")
        head.pack(fill="x")
        self.title = ttk.Label(head, text="", style="Title.TLabel")
        self.title.pack(anchor="w")
        self.notes = ttk.Label(head, text="", style="Muted.TLabel",
                               wraplength=800, justify="left")
        self.notes.pack(anchor="w", pady=(3, 6))

        statusrow = ttk.Frame(right, style="Card.TFrame")
        statusrow.pack(fill="x", pady=(0, 6))
        self.status = ttk.Label(statusrow, text="", style="Status.TLabel")
        self.status.pack(side="left")
        self.viol = ttk.Label(statusrow, text="", style="Card.TLabel", foreground=FAIL)
        self.viol.pack(side="left", padx=(14, 0))
        self.play = ttk.Button(statusrow, text="Pausa", width=8, command=self._toggle)
        self.play.pack(side="right")
        self.clock = ttk.Label(statusrow, text="", style="Muted.TLabel")
        self.clock.pack(side="right", padx=(0, 10))

        self.scv = tk.Canvas(right, bg=CARD, height=350, highlightthickness=0)
        self.scv.pack(fill="x", pady=(0, 6))

        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)
        plotf = ttk.Frame(nb, style="Card.TFrame")
        dataf = ttk.Frame(nb, style="Card.TFrame")
        nb.add(plotf, text="Grafico")
        nb.add(dataf, text="Dati")

        self.fig = Figure(figsize=(7.2, 2.4), dpi=100, facecolor=CARD)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plotf)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.table = ttk.Treeview(dataf, show="headings", height=6)
        self.table.pack(fill="both", expand=True)

        self.signal = ttk.Combobox(statusrow, state="readonly", width=13)
        self.signal.pack(side="right", padx=(0, 8))
        self.signal.bind("<<ComboboxSelected>>", lambda e: self._plot())
        ttk.Label(statusrow, text="Segnale", style="Muted.TLabel").pack(
            side="right", padx=(0, 4))

    def _check_all(self):
        current = self.list.curselection()
        keep = current[0] if current else 0
        self.results = {}
        passed = 0
        self.list.delete(0, "end")
        for eid in self.ids:
            try:
                raw = json.loads((DATA / "exercises" / f"{eid}.json").read_text(encoding="utf-8"))
                circ = from_dict(raw, self.db)
                res = simulate(circ)
                check(circ, res)
                ok = res.ok
            except Exception:
                ok = False
            self.results[eid] = ok
            passed += ok
            self.list.insert("end", f"  {'PASS' if ok else 'FAIL'}   {eid}")
            self.list.itemconfig("end", foreground=OK if ok else FAIL)
        self.summary.configure(text=f"{passed}/{len(self.ids)} test superati")
        if self.list.size():
            self.list.selection_set(min(keep, self.list.size() - 1))

    def _on_select(self, _event=None):
        sel = self.list.curselection()
        if not sel:
            return
        eid = self.ids[sel[0]]
        raw = json.loads((DATA / "exercises" / f"{eid}.json").read_text(encoding="utf-8"))
        self.circ = from_dict(raw, self.db)
        self.res = simulate(self.circ)
        check(self.circ, self.res)
        self.t_anim = 0.0
        self.schem = Schematic(self.scv, self.circ, LAYOUTS.get(eid), self.res)
        self._fill()
        self._plot()

    def _fill(self):
        c, r = self.circ, self.res
        self.title.configure(text=f"{c.id} - {c.title}")
        self.notes.configure(text=c.notes)
        if r.ok:
            self.status.configure(text="TEST SUPERATO", foreground=OK)
        elif r.checks:
            self.status.configure(text="TEST FALLITO", foreground=FAIL)
        else:
            self.status.configure(text="SIMULAZIONE", foreground=MUTED)
        self.viol.configure(text=" | ".join(v["message"] for v in r.violations))

        for item in self.table.get_children():
            self.table.delete(item)
        if r.analysis == "dc":
            self.table["columns"] = ("pid", "corrente", "tensione", "potenza")
            for col, txt, w in (("pid", "Componente", 200), ("corrente", "Corrente", 120),
                                ("tensione", "Tensione", 120), ("potenza", "Potenza", 120)):
                self.table.heading(col, text=txt)
                self.table.column(col, width=w, anchor="center")
            for pid, p in c.parts.items():
                self.table.insert("", "end", values=(
                    f"{pid} {p.name}", fmt(r.currents[pid], "A"),
                    fmt(report.part_voltage(c, r, pid), "V"), fmt(r.power[pid], "W")))
            self.signal.configure(values=[], state="disabled")
            self.signal.set("")
        else:
            self.table["columns"] = ("sig", "min", "max", "fine")
            for col, txt, w in (("sig", "Segnale", 130), ("min", "min", 120),
                                ("max", "max", 120), ("fine", "finale", 120)):
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
        best, rng = None, -1.0
        for s, arr in self.res.waves.items():
            if not s.startswith("V("):
                continue
            d = float(arr.max() - arr.min())
            if d > rng:
                best, rng = s, d
        return best or next(iter(self.res.waves), "")

    def _plot(self):
        r = self.res
        ax = self.ax
        ax.clear()
        ax.set_facecolor(CARD)
        for spine in ax.spines.values():
            spine.set_color("#d9dee8")
        ax.tick_params(colors=MUTED, labelsize=8)
        ax.grid(True, color="#e6e9f0", linewidth=0.8)
        ax.set_axisbelow(True)
        self.vline = None

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
                        fontsize=9, color=TEXT)
            if vals:
                lo = min(0, min(vals))
                hi = max(0, max(vals))
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
                self.vline = ax.axvline(self.t_anim, color="#94a3b8", linewidth=0.9,
                                        linestyle=":")
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _toggle(self):
        self.playing = not self.playing
        self.play.configure(text="Pausa" if self.playing else "Riprendi")

    def _tick(self):
        now = time.perf_counter()
        d = min(0.1, now - self.last)
        self.last = now
        if self.res is not None and self.schem is not None:
            if self.playing and self.res.time is not None:
                span = max(3.0, min(8.0, float(self.res.time[-1])))
                self.t_anim += d * (float(self.res.time[-1]) / span)
                if self.t_anim > float(self.res.time[-1]):
                    self.t_anim = 0.0
            t = self.t_anim if self.res.time is not None else None
            self.schem.draw(t, d if self.playing else 0.0, self.playing)
            if t is not None:
                self.clock.configure(text=f"t = {self.t_anim:.2f} s")
                self.play.configure(state="normal")
            else:
                self.clock.configure(text="DC")
                self.play.configure(state="normal")
            self.frame += 1
            if t is not None and self.vline is not None and self.frame % 4 == 0:
                self.vline.set_xdata([t, t])
                self.canvas.draw_idle()
        self.root.after(33, self._tick)


def main(eid=None):
    root = tk.Tk()
    App(root, eid)
    root.mainloop()


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)
