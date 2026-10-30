from pathlib import Path
import tkinter as tk

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
SLOW_EXERCISES = {"exp11", "exp11b", "exp11c", "exp11d", "buck", "buck_reg", "buck_5a", "alimentatore", "carica_solare"}
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
    "LAMP": "Lampadine",
    "XFMR": "Trasformatori",
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
