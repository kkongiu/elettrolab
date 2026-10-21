import math

import numpy as np

from .breadboards import BOARD, COL_X, COLS, H, RAIL_COLORS, RAIL_Y, ROWS, ROW_Y, W, hole_xy
from .units import fmt

BG = "#f7f2e6"
HOLE = "#cfc7b7"
HOLE_EDGE = "#a89f8f"
INK = "#222222"
WIRE = "#555555"
TEXT = "#4b5563"
FONT = "DejaVu Sans"
NET_COLORS = ["#c92a2a", "#1864ab", "#2b8a3e", "#9c36b5", "#e8590c", "#0c8599", "#5f3dc4"]


def _blend(c1, c2, t):
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Breadboard:
    def __init__(self, canvas, doc, res, layout):
        self.c = canvas
        self.doc = doc
        self.res = res
        self.layout = layout
        self.s = 1.0
        self.ox = 0.0
        self.oy = 0.0

    def T(self, x, y):
        return (self.ox + x * self.s, self.oy + y * self.s)

    def line(self, pts, color=INK, width=2.0):
        flat = []
        for x, y in pts:
            X, Y = self.T(x, y)
            flat.extend((X, Y))
        return self.c.create_line(*flat, fill=color, width=max(1.0, width * self.s),
                                  capstyle="round")

    def text(self, x, y, txt, anchor="center", color=TEXT, size=8):
        return self.c.create_text(*self.T(x, y), text=txt, anchor=anchor,
                                  fill=color, font=(FONT, size))

    def _cur(self, pid, t):
        if self.res is None:
            return 0.0
        if self.res.time is None or t is None:
            return float(self.res.currents.get(pid, 0.0))
        key = f"I({pid})"
        if key not in self.res.waves:
            return 0.0
        return float(np.interp(t, self.res.time, self.res.waves[key]))

    def _pin_xy(self, pid, pin):
        return hole_xy(self.layout["parts"][pid]["pins"][pin])

    def _net_color(self, net):
        if net == self.doc.ground:
            return "#343a40"
        names = [n for n in self.doc.nets if n != self.doc.ground]
        i = names.index(net) if net in names else 0
        return NET_COLORS[i % len(NET_COLORS)]

    def _label(self, pid):
        p = self.doc.part(pid)
        if p is None:
            return pid
        k = p.kind
        if k == "R":
            return f"{pid} {fmt(p.num('r'), 'Ω')}"
        if k == "V":
            return f"{pid} {fmt(p.num('v'), 'V')}"
        if k == "LED":
            return pid
        if k == "C":
            c = p.num("c")
            return f"{pid} {c * 1e6:g} µF" if c <= 1e-3 else f"{pid} {c:g} F"
        if k == "SW":
            return pid
        if k == "L":
            return f"{pid} {fmt(p.num('l'), 'H')}"
        return pid

    def draw(self, t=None, dreal=0.0, playing=True):
        c = self.c
        c.delete("all")
        if not self.layout:
            self.text(W / 2, H / 2, "Breadboard non disponibile per questo esercizio",
                      size=11, color=TEXT)
            return
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 200 or h < 150:
            w, h = 860, 340
        self.s = min(w / W, h / H)
        self.ox = (w - W * self.s) / 2
        self.oy = (h - H * self.s) / 2
        self._board()
        self._wires()
        for pid in self.layout.get("parts", {}):
            if pid in self.doc.parts:
                self._part(pid, t)
        self.text(52, 412, "breadboard virtuale: colore del filo = rete", anchor="w",
                  color=TEXT, size=7)

    def _board(self):
        x0, y0, x1, y1 = BOARD
        self.c.create_rectangle(*self.T(x0, y0), *self.T(x1, y1),
                                fill=BG, outline="#cfc6b2", width=1.5)
        self.c.create_rectangle(*self.T(x0 + 6, 214), *self.T(x1 - 6, 246),
                                fill="#efe8d8", outline="")
        for row in ROWS:
            y = ROW_Y[row]
            self.text(74, y, row, size=8)
            for col in range(1, COLS + 1):
                X, Y = self.T(COL_X[col], y)
                r = max(1.8, 2.7 * self.s)
                self.c.create_oval(X - r, Y - r, X + r, Y + r,
                                   fill=HOLE, outline=HOLE_EDGE, width=max(0.7, 0.9 * self.s))
        for col in range(1, COLS + 1):
            if col == 1 or col % 5 == 0:
                self.text(COL_X[col], 44, str(col), size=7)
        for rail, y in RAIL_Y.items():
            color = RAIL_COLORS[rail]
            self.line([(82, y), (820, y)], color=color, width=2.2)
            self.text(64, y, "+" if rail.endswith("+") else "-", color=color, size=9)
            for col in range(1, COLS + 1):
                X, Y = self.T(COL_X[col], y)
                r = max(1.5, 2.3 * self.s)
                self.c.create_oval(X - r, Y - r, X + r, Y + r,
                                   fill=color, outline="")

    def _wires(self):
        for wire in self.layout.get("wires", []):
            pts = [hole_xy(p) for p in wire.get("points", [])]
            if len(pts) < 2:
                continue
            color = self._net_color(wire.get("net", ""))
            if len(pts) == 2:
                (x1, y1), (x2, y2) = pts
                dx, dy = x2 - x1, y2 - y1
                L = math.hypot(dx, dy) or 1
                nx, ny = -dy / L, dx / L
                ctrl = ((x1 + x2) / 2 + nx * 14, (y1 + y2) / 2 + ny * 14)
                p1 = self.T(*pts[0])
                pc = self.T(*ctrl)
                p2 = self.T(*pts[1])
                self.c.create_line(p1[0], p1[1], pc[0], pc[1], p2[0], p2[1],
                                   smooth=True, fill=color,
                                   width=max(1.3, 2.4 * self.s), capstyle="round")
            else:
                self.line(pts, color=color, width=2.2)

    def _part(self, pid, t):
        p = self.doc.part(pid)
        if p is None:
            return
        pins = self.layout["parts"][pid].get("pins", {})
        if p.kind == "V":
            self._battery(pid, p)
            return
        points = [(pin, hole_xy(pins[pin])) for pin in p.spec.pins if pin in pins]
        if p.kind == "GND":
            if points:
                self._ground(points[0][1])
            return
        if len(points) < 2:
            return
        if len(p.spec.pins) >= 3:
            self._module(pid, p, points)
            return
        a, b = points[0][1], points[1][1]
        kind = p.kind
        if kind == "LED":
            self._led(pid, p, a, b, t)
        elif kind == "R":
            self._resistor(pid, p, a, b)
        elif kind == "C":
            self._capacitor(pid, p, a, b)
        elif kind == "L":
            self._inductor(pid, p, a, b)
        elif kind == "SW":
            self._switch(pid, p, a, b)
        else:
            self._module(pid, p, points)

    def _geometry(self, a, b):
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1
        ux, uy = dx / L, dy / L
        nx, ny = -uy, ux
        return mx, my, L, ux, uy, nx, ny

    def _resistor(self, pid, p, a, b):
        mx, my, L, ux, uy, nx, ny = self._geometry(a, b)
        self.line([a, (mx - ux * L * 0.25, my - uy * L * 0.25)], color=INK, width=2)
        self.line([(mx + ux * L * 0.25, my + uy * L * 0.25), b], color=INK, width=2)
        pts = []
        for u, v in ((-0.25, -8), (0.25, -8), (0.25, 8), (-0.25, 8)):
            pts.append((mx + ux * L * u + nx * v, my + uy * L * u + ny * v))
        self.c.create_polygon(*[c for p in pts for c in self.T(*p)],
                              outline=INK, fill="#f3d9b1", width=max(1.0, 1.5 * self.s))
        self.text(mx - nx * 22, my - ny * 22, self._label(pid), size=8)

    def _led(self, pid, p, a, b, t):
        mx, my, L, ux, uy, nx, ny = self._geometry(a, b)
        i = abs(self._cur(pid, t))
        imax = float(p.get("imax", 0.03))
        burned = bool(self.res and any(v.get("part") == pid and v["code"] == "burned"
                                       for v in self.res.violations))
        if not burned and i > 1e-6:
            r = math.log10(max(i / 1e-6, 1.0)) / math.log10(max(imax / 1e-6, 10.0))
            r = min(1.0, max(0.0, r))
            for rad, f in ((26, 0.30), (18, 0.45), (11, 0.65)):
                X, Y = self.T(mx, my)
                rr = rad * self.s
                self.c.create_oval(X - rr, Y - rr, X + rr, Y + rr,
                                   fill=_blend(BG, "#ef4444", r * f), outline="")
        self.line([a, (mx - ux * L * 0.18, my - uy * L * 0.18)], color=INK, width=2)
        self.line([(mx + ux * L * 0.18, my + uy * L * 0.18), b], color=INK, width=2)
        tri = [(-0.18, -8), (-0.18, 8), (0.16, 0)]
        poly = [(mx + ux * L * u + nx * v, my + uy * L * u + ny * v) for u, v in tri]
        self.c.create_polygon(*[c for p in poly for c in self.T(*p)],
                              outline=INK, fill="", width=max(1.0, 1.5 * self.s))
        self.line([(mx + ux * L * 0.16 + nx * -8, my + uy * L * 0.16 + ny * -8),
                   (mx + ux * L * 0.16 + nx * 8, my + uy * L * 0.16 + ny * 8)],
                  color=INK, width=2)
        if burned:
            X, Y = self.T(mx, my)
            r = 10 * self.s
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill="#3f1a1a", outline="")
            self.c.create_line(X - r, Y - r, X + r, Y + r, fill="#fca5a5", width=2)
            self.c.create_line(X - r, Y + r, X + r, Y - r, fill="#fca5a5", width=2)
        self.text(mx - nx * 24, my - ny * 24, self._label(pid), size=8)
        self.text(mx + nx * 22, my + ny * 22, f"I={fmt(i, 'A')}", size=7, color="#b45309")

    def _capacitor(self, pid, p, a, b):
        mx, my, L, ux, uy, nx, ny = self._geometry(a, b)
        self.line([a, (mx - ux * 6, my - uy * 6)], color=INK, width=2)
        self.line([(mx + ux * 6, my + uy * 6), b], color=INK, width=2)
        for s in (-1, 1):
            self.line([(mx + ux * 6 * s + nx * -9, my + uy * 6 * s + ny * -9),
                       (mx + ux * 6 * s + nx * 9, my + uy * 6 * s + ny * 9)],
                      color=INK, width=2)
        self.text(mx - nx * 22, my - ny * 22, self._label(pid), size=8)

    def _inductor(self, pid, p, a, b):
        mx, my, L, ux, uy, nx, ny = self._geometry(a, b)
        self.line([a, b], color=INK, width=2)
        body = [(-0.2, -7), (0.2, -7), (0.2, 7), (-0.2, 7)]
        poly = [(mx + ux * L * u + nx * v, my + uy * L * u + ny * v) for u, v in body]
        self.c.create_polygon(*[c for p in poly for c in self.T(*p)],
                              outline=INK, fill="", width=max(1.0, 1.4 * self.s))
        self.text(mx - nx * 22, my - ny * 22, self._label(pid), size=8)

    def _switch(self, pid, p, a, b):
        mx, my, L, ux, uy, nx, ny = self._geometry(a, b)
        for pt in (a, b):
            X, Y = self.T(*pt)
            r = max(1.6, 2.4 * self.s)
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=INK, outline="")
        end = (mx + ux * L * 0.28 + nx * -8, my + uy * L * 0.28 + ny * -8)
        self.line([a, end], color=INK, width=2)
        self.text(mx - nx * 22, my - ny * 22, self._label(pid), size=8)

    def _ground(self, pt):
        x, y = pt
        self.line([(x, y), (x, y + 12)], color=INK, width=2)
        for w, dy in ((11, 12), (7, 17), (3, 22)):
            self.line([(x - w, y + dy), (x + w, y + dy)], color=INK, width=2)

    @staticmethod
    def _rail_hole(name):
        return name.startswith(("T+", "T-", "B+", "B-"))

    def _module(self, pid, p, points):
        hole_map = self.layout["parts"][pid].get("pins", {})
        body = [(pin, pt) for pin, pt in points if not self._rail_hole(hole_map.get(pin, ""))]
        if len(body) < 2:
            body = list(points)
        xs = [pt[0] for _, pt in body]
        ys = [pt[1] for _, pt in body]
        pad = 16
        x0, x1 = min(xs) - pad, max(xs) + pad
        y0, y1 = min(ys) - pad, max(ys) + pad
        self.c.create_rectangle(*self.T(x0, y0), *self.T(x1, y1),
                                outline=INK, fill="#e9ecef",
                                width=max(1.0, 1.4 * self.s))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for pin, pt in points:
            if self._rail_hole(hole_map.get(pin, "")):
                self.line([(cx, cy), pt], color=INK, width=1.5)
            X, Y = self.T(*pt)
            r = max(1.2, 1.8 * self.s)
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=INK, outline="")
            self.text(pt[0], pt[1] + 12, pin, size=6)
        self.text(cx, y0 - 6, pid, size=8, color=INK)

    def _battery(self, pid, p):
        pos = self.layout["parts"][pid].get("pos", (60, 200))
        x, y = pos
        self.c.create_rectangle(*self.T(x, y - 32), *self.T(x + 40, y + 32),
                                fill="#343a40", outline=INK)
        self.text(x + 20, y - 12, "+", color="#ffffff", size=12)
        self.text(x + 20, y + 14, "-", color="#ffffff", size=12)
        self.text(x + 20, y + 40, self._label(pid), size=8)
        plus = hole_xy(self.layout["parts"][pid]["pins"]["+"])
        minus = hole_xy(self.layout["parts"][pid]["pins"]["-"])
        self.line([(x + 40, y - 18), plus], color="#c92a2a", width=2)
        self.line([(x + 40, y + 18), minus], color="#343a40", width=2)
