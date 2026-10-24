import math

import numpy as np

from .layouts import H, W
from .units import fmt

INK = "#1f2937"
WIRE = "#64748b"
SEL = "#e11d48"
MUTED = "#6b7280"
DOT = "#f59e0b"
RED = "#ef4444"
BG = "#ffffff"
FONT = "DejaVu Sans"


def _blend(c1, c2, t):
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Path:
    def __init__(self, poly, key, pid, pin):
        self.poly = [(float(x), float(y)) for x, y in poly]
        self.key = key
        self.net = key.split("|")[0]
        self.pid = pid
        self.pin = pin
        self.cum = [0.0]
        for a, b in zip(self.poly, self.poly[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.total = self.cum[-1]

    def at(self, d):
        if self.total <= 0:
            return self.poly[0]
        d %= self.total
        for i in range(1, len(self.cum)):
            if d <= self.cum[i]:
                a, b = self.poly[i - 1], self.poly[i]
                seg = self.cum[i] - self.cum[i - 1]
                f = 0.0 if seg <= 0 else (d - self.cum[i - 1]) / seg
                return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        return self.poly[-1]


class Schematic:
    def __init__(self, canvas, doc, res=None):
        self.c = canvas
        self.doc = doc
        self.layout = doc.layout
        self.res = res
        self.s = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self.paths = []
        self.rail = None
        self.buses = []
        self.junctions = []
        self.cross = {}
        self.gaps = []
        self.led_glow = {}
        self.dreal = 0.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.view_w = 860
        self.view_h = 340
        self.phase = {}
        self.sel_net = None
        if self.layout and self.layout.get("parts"):
            self._build_routes()
            self._compute_crossings()

    def virtual(self, x, y):
        if self.s <= 0:
            return (x, y)
        return ((x - self.ox) / self.s, (y - self.oy) / self.s)

    def zoom_at(self, cx, cy, factor):
        wx = (cx - self.ox) / self.s if self.s > 0 else 0.0
        wy = (cy - self.oy) / self.s if self.s > 0 else 0.0
        self.zoom = max(0.2, min(8.0, self.zoom * factor))
        base = min(self.view_w / W, self.view_h / H)
        s2 = base * self.zoom
        ox2 = (self.view_w - W * s2) / 2
        oy2 = (self.view_h - H * s2) / 2
        self.pan_x = cx - ox2 - wx * s2
        self.pan_y = cy - oy2 - wy * s2

    def pan_by(self, dx, dy):
        self.pan_x += dx
        self.pan_y += dy

    def reset_view(self):
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

    def pin_position(self, pid, pin):
        return self._pin(pid, pin)

    def pin_at(self, vx, vy, radius=13):
        best = None
        best_d = radius
        for pid in self.layout.get("parts", {}):
            if pid not in self.doc.parts:
                continue
            for pin in self.doc.pins(pid):
                px, py = self._pin(pid, pin)
                d = math.hypot(px - vx, py - vy)
                if d < best_d:
                    best, best_d = (pid, pin), d
        return best

    def part_bbox(self, pid):
        x, y, rot = self.layout["parts"].get(pid, (0, 0, 0))
        kind = self.doc.kind(pid)
        if kind == "RELAY2":
            return (x - 110, y - 92, x + 112, y + 92)
        if kind == "RELAY":
            return (x - 90, y - 62, x + 92, y + 62)
        if kind == "POT":
            return (x - 55, y - 58, x + 55, y + 22)
        if kind == "GND":
            return (x - 30, y - 32, x + 32, y + 22)
        if kind == "NPN":
            return (x - 50, y - 50, x + 50, y + 50)
        if kind == "PUT":
            return (x - 50, y - 50, x + 50, y + 50)
        if kind == "MOS":
            return (x - 50, y - 50, x + 50, y + 50)
        if kind == "XFMR":
            return (x - 80, y - 55, x + 80, y + 55)
        if rot in (90, 270):
            w, h = 36, 58
        else:
            w, h = 58, 36
        return (x - w, y - h, x + w, y + h)

    def part_at(self, vx, vy):
        for pid in reversed(list(self.layout.get("parts", {}))):
            if pid not in self.doc.parts:
                continue
            x0, y0, x1, y1 = self.part_bbox(pid)
            if x0 <= vx <= x1 and y0 <= vy <= y1:
                return pid
        return None

    def wire_at(self, vx, vy, radius=9):
        best, best_d = None, radius

        def dist(p, a, b):
            ax, ay = a
            bx, by = b
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            if l2 <= 0:
                return math.hypot(p[0] - ax, p[1] - ay)
            f = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
            return math.hypot(p[0] - (ax + f * dx), p[1] - (ay + f * dy))

        if self.rail:
            x0, x1, y = self.rail
            d = dist((vx, vy), (x0, y), (x1, y))
            if d < best_d:
                best, best_d = (self.doc.ground or "gnd"), d
        for name, x0, x1, y in self.buses:
            d = dist((vx, vy), (x0, y), (x1, y))
            if d < best_d:
                best, best_d = name, d
        for path in self.paths:
            for a, b in zip(path.poly, path.poly[1:]):
                d = dist((vx, vy), a, b)
                if d < best_d:
                    best, best_d = path.net, d
        return best

    def _loc(self, x, y, rot, u, v):
        if rot == 90:
            return (x - v, y + u)
        if rot == 180:
            return (x - u, y - v)
        if rot == 270:
            return (x + v, y - u)
        return (x + u, y + v)

    def _pin(self, pid, pin):
        x, y, rot = self.layout["parts"][pid]
        p = self.doc.part(pid)
        if p is None:
            return (x, y)
        pins = p.spec.pins
        if p.kind == "GND":
            return (x, y - 24)
        if p.kind == "RELAY2":
            offs = {"COIL+": (-70, -80), "COIL-": (-70, 80),
                    "COM1": (-30, -80), "NC1": (20, -80), "NO1": (100, -40),
                    "COM2": (-30, 80), "NC2": (20, 80), "NO2": (100, 40)}
            dx, dy = offs[pin]
            return (x + dx, y + dy)
        if p.kind == "POT":
            if pin == pins[0]:
                return self._loc(x, y, rot, -45, 0)
            if pin == pins[1]:
                return self._loc(x, y, rot, 45, 0)
            return self._loc(x, y, rot, 0, -45)
        if p.kind == "RELAY":
            offs = {"COIL+": (-50, -50), "COIL-": (-50, 50),
                    "COM": (10, -50), "NC": (60, -50), "NO": (80, 0)}
            dx, dy = offs[pin]
            return (x + dx, y + dy)
        if p.kind == "NPN":
            offs = {"C": (0, -45), "B": (-45, 0), "E": (26, 26)}
            dx, dy = offs[pin]
            return self._loc(x, y, rot, dx, dy)
        if p.kind == "PUT":
            offs = {"A": (0, -45), "G": (-45, 0), "K": (0, 45)}
            dx, dy = offs[pin]
            return self._loc(x, y, rot, dx, dy)
        if p.kind == "MOS":
            offs = {"D": (0, -45), "G": (-45, 0), "S": (0, 45)}
            dx, dy = offs[pin]
            return self._loc(x, y, rot, dx, dy)
        if p.kind == "SW" and pin == "FB":
            return self._loc(x, y, rot, -30, -45)
        if p.kind == "SW" and pin == "FF":
            return self._loc(x, y, rot, 30, -45)
        if p.kind == "XFMR":
            offs = {"P+": (-70, -40), "P-": (-70, 40),
                    "S+": (70, -40), "S-": (70, 40)}
            dx, dy = offs[pin]
            return self._loc(x, y, rot, dx, dy)
        i = pins.index(pin)
        return self._loc(x, y, rot, -45 if i == 0 else 45, 0)

    def _refs(self, net):
        out = []
        for ref in self.doc.nets[net]:
            pid, pin = ref.rsplit(".", 1)
            out.append((pid, pin))
        return out

    def _build_routes(self):
        routes = self.layout.get("routes", {})
        for net in self.doc.nets:
            refs = self._refs(net)
            pts = [self._pin(pid, pin) for pid, pin in refs]
            if net == self.doc.ground:
                ys = self.layout.get("gnd_y", 340)
                xs = [p[0] for p in pts]
                self.rail = (min(xs) - 20, max(xs) + 20, ys)
                for i, ((pid, pin), pt) in enumerate(zip(refs, pts)):
                    self.paths.append(Path([pt, (pt[0], ys)], f"{net}|{i}", pid, pin))
                    self.junctions.append(pt)
                continue
            if net in routes:
                for i, poly in enumerate(routes[net]):
                    self.paths.append(Path(poly, f"{net}|{i}", refs[0][0], refs[0][1]))
                self.junctions.extend(pts)
                continue
            if len(pts) == 2:
                p, q = pts
                if abs(q[0] - p[0]) >= abs(q[1] - p[1]):
                    poly = [p, (q[0], p[1]), q]
                else:
                    poly = [p, (p[0], q[1]), q]
                self.paths.append(Path(poly, f"{net}|0", refs[0][0], refs[0][1]))
            else:
                ys = sum(p[1] for p in pts) / len(pts)
                xs = [p[0] for p in pts]
                self.buses.append((net, min(xs) - 10, max(xs) + 10, ys))
                for i, ((pid, pin), pt) in enumerate(zip(refs, pts)):
                    self.paths.append(Path([pt, (pt[0], ys)], f"{net}|{i}", pid, pin))
                    self.junctions.append(pt)

    def T(self, x, y):
        return (self.ox + x * self.s, self.oy + y * self.s)

    def flat(self, pts):
        out = []
        for x, y in pts:
            X, Y = self.T(x, y)
            out.extend((X, Y))
        return out

    def line(self, pts, color=INK, width=2.0, dash=None, capstyle="round"):
        args = dict(fill=color, width=max(1.1, width * self.s), capstyle=capstyle)
        if dash:
            args["dash"] = dash
        return self.c.create_line(*self.flat(pts), **args)

    @staticmethod
    def _orient(a, b):
        if abs(a[1] - b[1]) < 1e-9:
            return "H"
        if abs(a[0] - b[0]) < 1e-9:
            return "V"
        return None

    @staticmethod
    def _interior(p, a, b):
        if abs(a[1] - b[1]) < 1e-9:
            return (abs(p[1] - a[1]) < 1e-9 and
                    min(a[0], b[0]) < p[0] < max(a[0], b[0]))
        if abs(a[0] - b[0]) < 1e-9:
            return (abs(p[0] - a[0]) < 1e-9 and
                    min(a[1], b[1]) < p[1] < max(a[1], b[1]))
        return False

    @staticmethod
    def _cross_hv(h1, h2, v1, v2):
        hy = h1[1]
        vx = v1[0]
        if (min(h1[0], h2[0]) < vx < max(h1[0], h2[0]) and
                min(v1[1], v2[1]) < hy < max(v1[1], v2[1])):
            return (vx, hy)
        return None

    def _compute_crossings(self):
        segs = []
        if self.rail:
            x0, x1, y = self.rail
            segs.append((self.doc.ground or "gnd", (x0, y), (x1, y), None, 0))
        for name, x0, x1, y in self.buses:
            segs.append((name, (x0, y), (x1, y), None, 0))
        for p in self.paths:
            for i, (a, b) in enumerate(zip(p.poly, p.poly[1:])):
                segs.append((p.net, a, b, p, i))
        dots = {tuple(j) for j in self.junctions}
        self.cross = {}
        self.gaps = []
        for i in range(len(segs)):
            n1, a1, b1, p1, i1 = segs[i]
            o1 = self._orient(a1, b1)
            if o1 is None:
                continue
            for j in range(i + 1, len(segs)):
                n2, a2, b2, p2, i2 = segs[j]
                o2 = self._orient(a2, b2)
                if o2 is None:
                    continue
                if o1 != o2:
                    h1, h2 = (a1, b1) if o1 == "H" else (a2, b2)
                    v1, v2 = (a1, b1) if o1 == "V" else (a2, b2)
                    pt = self._cross_hv(h1, h2, v1, v2)
                    if pt:
                        if n1 == n2:
                            dots.add(pt)
                        else:
                            vp = p1 if o1 == "V" else p2
                            vi = i1 if o1 == "V" else i2
                            if vp is not None:
                                self.cross.setdefault((vp.key, vi), []).append(pt)
                                self.gaps.append((pt, h1, h2))
                if n1 == n2:
                    for p in (a1, b1):
                        if self._interior(p, a2, b2):
                            dots.add(p)
                    for p in (a2, b2):
                        if self._interior(p, a1, b1):
                            dots.add(p)
        self.junctions = sorted(dots)

    def _draw_path(self, path):
        sel = path.net == self.sel_net
        color = SEL if sel else WIRE
        width = 3.0 if sel else 1.9
        for i, (a, b) in enumerate(zip(path.poly, path.poly[1:])):
            splits = self.cross.get((path.key, i), [])
            if not splits or abs(a[0] - b[0]) > 1e-9:
                self.line([a, b], color=color, width=width)
                continue
            x = a[0]
            y0, y1 = sorted((a[1], b[1]))
            cur = y0
            for _, cy in sorted(splits, key=lambda p: p[1]):
                top = max(y0, cy - 6)
                bot = min(y1, cy + 6)
                if top > cur:
                    self.line([(x, cur), (x, top)], color=color, width=width,
                              capstyle="butt")
                cur = max(cur, bot)
            if cur < y1:
                self.line([(x, cur), (x, y1)], color=color, width=width,
                          capstyle="butt")

    def text(self, x, y, txt, anchor="center", color=MUTED, size=9):
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

    def _volt(self, pid, pin, t):
        if self.res is None:
            return 0.0
        net = self.doc.net_of(pid, pin)
        if net is None:
            return 0.0
        if net == self.doc.ground:
            return 0.0
        if self.res.time is None or t is None:
            return float(self.res.nodes.get(net, 0.0))
        key = f"V({net})"
        return float(np.interp(t, self.res.time, self.res.waves[key]))

    def _state(self, pid, t):
        p = self.doc.part(pid)
        if p is None or self.res is None:
            return ""
        i = self._cur(pid, t)
        kind = p.kind
        if kind == "LED":
            burned = any(v.get("part") == pid and v["code"] == "burned"
                         for v in self.res.violations)
            if burned:
                return "bruciato"
            return "acceso" if i > 1e-6 else "spento"
        if kind == "D":
            return "conduce" if i > 1e-6 else "interdetto"
        if kind in ("NPN", "PUT", "MOS"):
            return "on" if i > 1e-6 else "off"
        if kind in ("RELAY", "RELAY2"):
            return "eccitato" if self._relay_on(pid, t) else "riposo"
        if kind == "SPK":
            return "suona" if abs(i) > 1e-6 else "silenzio"
        if kind == "LAMP":
            v = abs(self._volt(pid, "1", t) - self._volt(pid, "2", t))
            vn = p.num("vn") if "vn" in p.params else 12.0
            return "accesa" if v > 0.5 * vn else "spenta"
        return ""

    def _out(self, pid, pin, i):
        p = self.doc.part(pid)
        if p is None:
            return i
        first = p.spec.pins[0]
        if p.kind == "V":
            return i if pin == first else -i
        if p.kind == "MOS":
            if pin == "G":
                return 0.0
            return -i if pin == "D" else i
        return -i if pin == first else i

    def draw(self, t=None, dreal=0.0, playing=True):
        c = self.c
        self.dreal = dreal
        c.delete("all")
        if not self.layout or not self.layout.get("parts"):
            self.text(450, 200, "Nessun componente: aggiungine uno dalla palette", size=11)
            return
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 200 or h < 150:
            w, h = 860, 340
        self.view_w, self.view_h = w, h
        base = min(w / W, h / H)
        self.s = base * self.zoom
        self.ox = (w - W * self.s) / 2 + self.pan_x
        self.oy = (h - H * self.s) / 2 + self.pan_y

        if self.rail:
            x0, x1, y = self.rail
            gsel = self.sel_net == (self.doc.ground or "gnd")
            self.line([(x0, y), (x1, y)], color=SEL if gsel else WIRE,
                      width=3.0 if gsel else 2.2)
        for name, x0, x1, y in self.buses:
            bsel = self.sel_net == name
            self.line([(x0, y), (x1, y)], color=SEL if bsel else WIRE,
                      width=3.0 if bsel else 2.0)
        for path in self.paths:
            self._draw_path(path)
        for x, y in self.junctions:
            X, Y = self.T(x, y)
            r = 3.0 * self.s
            c.create_oval(X - r, Y - r, X + r, Y + r, fill=INK, outline="")

        for pid in self.layout["parts"]:
            if pid in self.doc.parts:
                self._draw_part(pid, t)

        for path in self.paths:
            self._dots(path, t, dreal, playing)
        for (x, y), h1, h2 in self.gaps:
            a = self.T(x, y - 6)
            b = self.T(x, y + 6)
            c.create_line(a[0], a[1], b[0], b[1], fill=BG,
                          width=max(2.8, 3.4 * self.s))
            self.line([h1, h2], color=WIRE, width=1.9)

    def _label(self, pid):
        p = self.doc.part(pid)
        if p is None:
            return pid
        k = p.kind
        if k == "R":
            return f"{pid}  {fmt(p.num('r'), '\u03a9')}"
        if k == "V":
            if p.get("wave") == "sin":
                amp = p.num("amp") if "amp" in p.params else 0.0
                freq = p.num("freq") if "freq" in p.params else 50.0
                return f"{pid}  {fmt(amp, 'V')} / {freq:g} Hz"
            return f"{pid}  {fmt(p.num('v'), 'V')}"
        if k == "LED":
            return f"{pid}  LED"
        if k == "D":
            return f"{pid}  D"
        if k == "SW":
            return f"{pid}  {'chiuso' if p.get('closed', True) else 'aperto'}"
        if k == "C":
            c = p.num("c")
            if c < 1e-6:
                return f"{pid}  {c * 1e9:g} nF"
            if c <= 1e-3:
                return f"{pid}  {c * 1e6:g} \u00b5F"
            if c < 1:
                return f"{pid}  {c * 1e3:g} mF"
            return f"{pid}  {c:g} F"
        if k == "L":
            return f"{pid}  {fmt(p.num('l'), 'H')}"
        if k == "POT":
            return f"{pid}  {fmt(p.num('rtotal'), '\u03a9')}"
        if k == "SPK":
            return f"{pid}  {fmt(p.num('r'), '\u03a9')}"
        if k == "LAMP":
            vn = p.num("vn") if "vn" in p.params else 12.0
            pw = p.num("p") if "p" in p.params else 0.0
            return f"{pid}  {vn:g} V {pw:g} W"
        if k == "XFMR":
            return f"{pid}  n={p.num('n'):.3g}"
        if k == "NPN":
            return f"{pid}  NPN"
        if k == "PUT":
            return f"{pid}  PUT"
        if k == "MOS":
            return f"{pid}  MOS"
        if k == "GND":
            return "GND"
        return pid

    def _draw_part(self, pid, t):
        p = self.doc.part(pid)
        if p is None:
            return
        x, y, rot = self.layout["parts"][pid]
        kind = p.kind
        if kind == "LED":
            viol = self.res.violations if self.res is not None else []
            burned = any(v.get("part") == pid and v["code"] == "burned" for v in viol)
            if burned:
                self._burn(x, y)
            else:
                self._led_glow(pid, x, y, t)
        if kind == "LAMP":
            self._lamp_glow(pid, x, y, t)
        if kind == "R":
            self._resistor(x, y, rot)
        elif kind == "LAMP":
            self._lamp(x, y, rot)
        elif kind == "C":
            self._capacitor(x, y, rot)
        elif kind == "L":
            self._inductor(x, y, rot)
        elif kind == "XFMR":
            self._transformer(x, y, rot)
        elif kind == "V":
            if p.get("wave") == "sin":
                self._ac_source(x, y, rot)
            else:
                self._battery(x, y, rot)
        elif kind == "SW":
            self._switch(pid, x, y, rot, t)
        elif kind == "LED":
            self._led(x, y, rot)
        elif kind == "D":
            self._diode(x, y, rot)
        elif kind == "POT":
            self._pot(x, y, rot)
        elif kind == "RELAY":
            self._relay(pid, x, y, t)
        elif kind == "RELAY2":
            self._relay(pid, x, y, t)
        elif kind == "NPN":
            self._npn(x, y, rot)
        elif kind == "PUT":
            self._put(x, y, rot)
        elif kind == "MOS":
            self._mosfet(x, y, rot)
        elif kind == "SPK":
            self._speaker(x, y, rot)
        elif kind == "GND":
            self._ground(x, y)

        i = self._cur(pid, t)
        state = self._state(pid, t)
        suffix = f"  \u00b7  {state}" if state else ""
        if kind == "GND":
            self.text(x + 16, y + 2, "GND", anchor="w", size=8, color=MUTED)
        elif kind == "NPN":
            self.text(x, y - 52, self._label(pid), anchor="s", size=9, color=INK)
            self.text(x, y + 52, f"I = {fmt(i, 'A')}{suffix}", anchor="n", size=8, color=DOT)
            self.text(*self._loc(x, y, rot, 10, -45), "C", anchor="w", size=7, color=MUTED)
            self.text(*self._loc(x, y, rot, -48, 3), "B", anchor="e", size=7, color=MUTED)
            self.text(*self._loc(x, y, rot, 34, 29), "E", anchor="w", size=7, color=MUTED)
        elif kind == "PUT":
            self.text(x, y - 52, self._label(pid), anchor="s", size=9, color=INK)
            self.text(x, y + 52, f"I = {fmt(i, 'A')}{suffix}", anchor="n", size=8, color=DOT)
            self.text(*self._loc(x, y, rot, 10, -45), "A", anchor="w", size=7, color=MUTED)
            self.text(*self._loc(x, y, rot, -48, 3), "G", anchor="e", size=7, color=MUTED)
            self.text(*self._loc(x, y, rot, 10, 45), "K", anchor="w", size=7, color=MUTED)
        elif kind == "MOS":
            self.text(x, y - 52, self._label(pid), anchor="s", size=9, color=INK)
            self.text(x, y + 52, f"I = {fmt(i, 'A')}{suffix}", anchor="n", size=8, color=DOT)
            self.text(*self._loc(x, y, rot, 8, -45), "D", anchor="w", size=7, color=MUTED)
            self.text(*self._loc(x, y, rot, -48, 3), "G", anchor="e", size=7, color=MUTED)
            self.text(*self._loc(x, y, rot, 8, 45), "S", anchor="w", size=7, color=MUTED)
        elif kind == "RELAY2":
            self.text(x, y + 100, f"{self._label(pid)}   I = {fmt(i, 'A')}{suffix}",
                      size=9, color=INK)
        elif kind == "RELAY":
            self.text(x, y + 64, f"{self._label(pid)}   I = {fmt(i, 'A')}{suffix}",
                      size=9, color=INK)
        elif kind == "LED":
            if rot in (90, 270):
                self.text(x + 40, y - 7, self._label(pid), anchor="w", size=9, color=INK)
                self.text(x + 40, y + 8, f"I = {fmt(i, 'A')}{suffix}", anchor="w", size=8, color=DOT)
            else:
                self.text(x, y - 40, self._label(pid), anchor="s", size=9, color=INK)
                self.text(x, y + 40, f"I = {fmt(i, 'A')}{suffix}", anchor="n", size=8, color=DOT)
        elif kind == "D":
            if rot in (90, 270):
                self.text(x + 40, y - 7, self._label(pid), anchor="w", size=9, color=INK)
                self.text(x + 40, y + 8, f"I = {fmt(i, 'A')}{suffix}", anchor="w", size=8, color=DOT)
            else:
                self.text(x, y - 40, self._label(pid), anchor="s", size=9, color=INK)
                self.text(x, y + 40, f"I = {fmt(i, 'A')}{suffix}", anchor="n", size=8, color=DOT)
        elif kind == "POT":
            self.text(x + 42, y - 14, self._label(pid), anchor="w", size=9, color=INK)
            self.text(x + 42, y + 2, f"I = {fmt(i, 'A')}{suffix}", anchor="w", size=8, color=DOT)
        elif rot in (90, 270):
            self.text(x + 24, y - 7, self._label(pid), anchor="w", size=9, color=INK)
            self.text(x + 24, y + 8, f"I = {fmt(i, 'A')}{suffix}", anchor="w", size=8, color=DOT)
        else:
            self.text(x, y - 26, self._label(pid), anchor="s", size=9, color=INK)
            self.text(x, y + 26, f"I = {fmt(i, 'A')}{suffix}", anchor="n", size=8, color=DOT)

    def _dots(self, path, t, dreal, playing):
        if path.total <= 0:
            return
        i = self._cur(path.pid, t)
        if abs(i) < 1e-7:
            return
        out = self._out(path.pid, path.pin, i)
        sign = 1.0 if out >= 0 else -1.0
        phase = self.phase.get(path.key, 0.0)
        if playing and dreal > 0:
            speed = 25.0 + 95.0 * min(1.0, abs(i) / 0.02)
            phase = (phase + dreal * speed * sign) % path.total
            self.phase[path.key] = phase
        n = max(1, int(path.total / 24.0))
        r = 2.4 * self.s
        for k in range(n):
            x, y = path.at(phase + k * 24.0)
            X, Y = self.T(x, y)
            self.c.create_oval(X - r, Y - r, X + r, Y + r,
                               fill=DOT, outline="")

    def _resistor(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -27, 0)])
        self.line([self._loc(x, y, rot, 27, 0), self._loc(x, y, rot, 45, 0)])
        body = [self._loc(x, y, rot, u, v)
                for u, v in ((-27, -9), (27, -9), (27, 9), (-27, 9))]
        self.c.create_polygon(*self.flat(body), outline=INK, fill="",
                              width=max(1.1, 1.8 * self.s))

    def _capacitor(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -7, 0)])
        self.line([self._loc(x, y, rot, 7, 0), self._loc(x, y, rot, 45, 0)])
        self.line([self._loc(x, y, rot, -7, -16), self._loc(x, y, rot, -7, 16)])
        self.line([self._loc(x, y, rot, 7, -16), self._loc(x, y, rot, 7, 16)])
        self.line([self._loc(x, y, rot, -19, -18), self._loc(x, y, rot, -11, -18)], width=1.2)
        self.line([self._loc(x, y, rot, -15, -22), self._loc(x, y, rot, -15, -14)], width=1.2)

    def _inductor(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -30, 0)])
        self.line([self._loc(x, y, rot, 30, 0), self._loc(x, y, rot, 45, 0)])
        if rot == 0:
            for k in range(4):
                u0 = -30 + k * 15
                a = self.T(*self._loc(x, y, 0, u0, -10))
                b = self.T(*self._loc(x, y, 0, u0 + 15, 10))
                self.c.create_arc(a[0], a[1], b[0], b[1], start=0, extent=180,
                                  style="arc", outline=INK,
                                  width=max(1.1, 1.7 * self.s))
        else:
            body = [self._loc(x, y, rot, u, v)
                    for u, v in ((-30, -9), (30, -9), (30, 9), (-30, 9))]
            self.c.create_polygon(*self.flat(body), outline=INK, fill="",
                                  width=max(1.1, 1.7 * self.s))

    def _transformer(self, x, y, rot):
        for dy in (-40, 40):
            self.line([self._loc(x, y, rot, -70, dy), self._loc(x, y, rot, -22, dy)])
            self.line([self._loc(x, y, rot, 70, dy), self._loc(x, y, rot, 22, dy)])
        for cx in (-20, 20):
            pts = [self._loc(x, y, rot, cx, -40)]
            for k in range(8):
                yy = -40 + (k + 1) * 10
                xx = cx + (6 if k % 2 == 0 else -6)
                pts.append(self._loc(x, y, rot, xx, yy))
            pts.append(self._loc(x, y, rot, cx, 40))
            self.line(pts, width=1.2)
        for cx in (-5, 5):
            self.line([self._loc(x, y, rot, cx, -45),
                       self._loc(x, y, rot, cx, 45)], width=1.0)
        for cx in (-20, 20):
            X, Y = self.T(*self._loc(x, y, rot, cx, -40))
            r = 2.2 * self.s
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=INK, outline="")

    def _battery(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -24, 0)])
        self.line([self._loc(x, y, rot, 24, 0), self._loc(x, y, rot, 45, 0)])
        for u, h, w in ((-24, 15, 2.4), (-12, 9, 1.7), (0, 15, 2.4), (12, 9, 1.7)):
            self.line([self._loc(x, y, rot, u, -h), self._loc(x, y, rot, u, h)], width=w)
        self.line([self._loc(x, y, rot, 12, 0), self._loc(x, y, rot, 24, 0)], width=1.4)
        self.text(*self._loc(x, y, rot, -34, -16), "+", size=10, color=INK)
        self.text(*self._loc(x, y, rot, 34, -16), "\u2212", size=10, color=INK)

    def _ac_source(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -18, 0)])
        self.line([self._loc(x, y, rot, 18, 0), self._loc(x, y, rot, 45, 0)])
        X, Y = self.T(x, y)
        r = 18 * self.s
        self.c.create_oval(X - r, Y - r, X + r, Y + r, outline=INK,
                           width=max(1.1, 1.8 * self.s))
        pts = [self._loc(x, y, rot, -10 + 20 * i / 12,
                         5 * math.sin(2 * math.pi * i / 12))
               for i in range(13)]
        self.line(pts, width=1.2)
        self.text(*self._loc(x, y, rot, -34, -16), "+", size=10, color=INK)
        self.text(*self._loc(x, y, rot, 34, -16), "\u2212", size=10, color=INK)

    def _sw_closed(self, pid, t):
        p = self.doc.part(pid)
        if p is None:
            return False
        if self.res is None or self.res.time is None or t is None:
            return bool(p.get("closed", True))
        closed = bool(p.get("closed", True))
        if "t_close" in p.params and t >= p.num("t_close"):
            closed = True
        if "t_open" in p.params and t >= p.num("t_open"):
            closed = False
        return closed

    def _switch(self, pid, x, y, rot, t):
        closed = self._sw_closed(pid, t)
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -27, 0)])
        self.line([self._loc(x, y, rot, 27, 0), self._loc(x, y, rot, 45, 0)])
        for u in (-27, 27):
            X, Y = self.T(*self._loc(x, y, rot, u, 0))
            r = 2.4 * self.s
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=INK, outline="")
        end = self._loc(x, y, rot, 27, 0) if closed else self._loc(x, y, rot, 18, -20)
        self.line([self._loc(x, y, rot, -27, 0), end], width=2.2)
        if not closed:
            X, Y = self.T(*end)
            r = 2.4 * self.s
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=BG, outline=INK)

    def _led(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -13, 0)])
        self.line([self._loc(x, y, rot, 8, 0), self._loc(x, y, rot, 45, 0)])
        tri = [self._loc(x, y, rot, -13, -13), self._loc(x, y, rot, -13, 13),
               self._loc(x, y, rot, 8, 0)]
        self.c.create_polygon(*self.flat(tri), outline=INK, fill="",
                              width=max(1.1, 1.8 * self.s))
        self.line([self._loc(x, y, rot, 8, -13), self._loc(x, y, rot, 8, 13)])
        for k in (-1, 1):
            a = self._loc(x, y, rot, 2, k * 16)
            b = self._loc(x, y, rot, 11, k * 25)
            self.line([a, b], width=1.1)

    def _lamp(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -18, 0)])
        self.line([self._loc(x, y, rot, 18, 0), self._loc(x, y, rot, 45, 0)])
        X, Y = self.T(x, y)
        r = 18 * self.s
        self.c.create_oval(X - r, Y - r, X + r, Y + r, outline=INK,
                           fill="", width=max(1.1, 1.6 * self.s))
        self.line([self._loc(x, y, rot, -9, -9), self._loc(x, y, rot, 9, 9)], width=1.1)
        self.line([self._loc(x, y, rot, -9, 9), self._loc(x, y, rot, 9, -9)], width=1.1)

    def _lamp_glow(self, pid, x, y, t):
        p = self.doc.part(pid)
        if p is None or self.res is None:
            return
        v = abs(self._volt(pid, "1", t) - self._volt(pid, "2", t))
        vn = p.num("vn") if "vn" in p.params else 12.0
        raw = max(0.0, min(1.0, (v / max(vn, 1e-9) - 0.3) / 0.7))
        prev = self.led_glow.get(pid, 0.0)
        if raw > 0.02:
            ratio = max(raw, prev)
        else:
            ratio = max(0.0, prev - self.dreal / 0.25)
        self.led_glow[pid] = ratio
        if ratio <= 0.01:
            return
        for rad, f in ((30, 0.30), (22, 0.50)):
            X, Y = self.T(x, y)
            r = rad * self.s
            self.c.create_oval(X - r, Y - r, X + r, Y + r,
                               fill=_blend(BG, DOT, ratio * f), outline="")

    def _diode(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -13, 0)])
        self.line([self._loc(x, y, rot, 8, 0), self._loc(x, y, rot, 45, 0)])
        tri = [self._loc(x, y, rot, -13, -13), self._loc(x, y, rot, -13, 13),
               self._loc(x, y, rot, 8, 0)]
        self.c.create_polygon(*self.flat(tri), outline=INK, fill="",
                              width=max(1.1, 1.8 * self.s))
        self.line([self._loc(x, y, rot, 8, -13), self._loc(x, y, rot, 8, 13)])

    def _led_glow(self, pid, x, y, t):
        i = abs(self._cur(pid, t))
        p = self.doc.part(pid)
        if p is None:
            return
        imax = float(p.get("imax", 0.03))
        viol = self.res.violations if self.res is not None else []
        burned = any(v.get("part") == pid and v["code"] == "burned" for v in viol)
        if burned:
            return
        if i < 1e-6:
            raw = 0.0
        else:
            raw = math.log10(max(i / 1e-6, 1.0)) / math.log10(max(imax / 1e-6, 10.0))
            raw = min(1.0, max(0.0, raw))
        prev = self.led_glow.get(pid, 0.0)
        if raw > 0.02:
            ratio = max(raw, prev)
        else:
            ratio = max(0.0, prev - self.dreal / 0.25)
        self.led_glow[pid] = ratio
        if ratio <= 0.01:
            return
        for rad, f in ((32, 0.30), (23, 0.45), (15, 0.65)):
            X, Y = self.T(x, y)
            r = rad * self.s
            col = _blend(BG, RED, ratio * f)
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=col, outline="")

    def _pot(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -30, 0)])
        self.line([self._loc(x, y, rot, 30, 0), self._loc(x, y, rot, 45, 0)])
        body = [self._loc(x, y, rot, u, v)
                for u, v in ((-30, -9), (30, -9), (30, 9), (-30, 9))]
        self.c.create_polygon(*self.flat(body), outline=INK, fill="",
                              width=max(1.1, 1.8 * self.s))
        self.line([self._loc(x, y, rot, 0, -45), self._loc(x, y, rot, 0, -10)])
        tri = [self._loc(x, y, rot, -5, -19), self._loc(x, y, rot, 5, -19),
               self._loc(x, y, rot, 0, -9)]
        self.c.create_polygon(*self.flat(tri), outline=INK, fill=INK)

    def _speaker(self, x, y, rot):
        self.line([self._loc(x, y, rot, -45, 0), self._loc(x, y, rot, -18, 0)])
        self.line([self._loc(x, y, rot, 18, 0), self._loc(x, y, rot, 30, 0)])
        body = [self._loc(x, y, rot, u, v)
                for u, v in ((-18, -14), (18, -14), (18, 14), (-18, 14))]
        self.c.create_polygon(*self.flat(body), outline=INK, fill="",
                              width=max(1.1, 1.8 * self.s))
        cone = [self._loc(x, y, rot, 18, -14), self._loc(x, y, rot, 18, 14),
                self._loc(x, y, rot, 30, 20), self._loc(x, y, rot, 30, -20)]
        self.c.create_polygon(*self.flat(cone), outline=INK, fill="",
                              width=max(1.1, 1.8 * self.s))
    def _ground(self, x, y):
        self.line([(x, y - 24), (x, y)], width=2.0)
        for w, dy in ((18, 0), (12, 5), (6, 10)):
            self.line([(x - w, y + dy), (x + w, y + dy)], width=2.0)

    def _npn(self, x, y, rot):
        def L(u, v):
            return self._loc(x, y, rot, u, v)
        r = 30
        self.c.create_oval(*self.flat([L(-r, -r), L(r, r)]), outline=INK, fill="",
                            width=max(1.1, 1.8 * self.s))
        self.line([L(0, -45), L(0, 0)])
        self.line([L(-45, 0), L(0, 0)])
        self.line([L(0, 0), L(18, 18)])
        tri = [L(26, 26), L(16, 20), L(20, 16)]
        self.c.create_polygon(*self.flat(tri), outline=INK, fill=INK)

    def _put(self, x, y, rot):
        def L(u, v):
            return self._loc(x, y, rot, u, v)
        r = 30
        self.c.create_oval(*self.flat([L(-r, -r), L(r, r)]), outline=INK, fill="",
                            width=max(1.1, 1.8 * self.s))
        self.line([L(0, -45), L(0, 45)])
        self.line([L(-45, 0), L(-8, 0)])
        tri = [L(0, 12), L(-8, 0), L(8, 0)]
        self.c.create_polygon(*self.flat(tri), outline=INK, fill=INK)

    def _mosfet(self, x, y, rot):
        def L(u, v):
            return self._loc(x, y, rot, u, v)
        self.line([L(0, -45), L(0, -18)])
        self.line([L(0, 45), L(0, 18)])
        self.line([L(-45, 0), L(-24, 0)])
        self.line([L(-24, -18), L(-24, 18)], width=1.6)
        for a, b in ((-18, -8), (-5, 5), (8, 18)):
            self.line([L(-12, a), L(-12, b)], width=2.0)
        self.line([L(0, -18), L(-12, -18)])
        self.line([L(0, 18), L(-12, 18)])
        self.line([L(0, 0), L(-12, 0)], width=1.3)
        tri = [L(-10, 0), L(-4, -4), L(-4, 4)]
        self.c.create_polygon(*self.flat(tri), outline=INK, fill=INK)

    def _relay_on(self, pid, t):
        if self.res is None:
            return False
        states = getattr(self.res, "relay_states", None)
        st = states.get(pid) if states else None
        if st is not None:
            if isinstance(st, np.ndarray) and self.res.time is not None and t is not None:
                return bool(np.interp(t, self.res.time, st) >= 0.5)
            return bool(st)
        vc = self._volt(pid, "COIL+", t) - self._volt(pid, "COIL-", t)
        p = self.doc.part(pid)
        return vc > float(p.get("vpull", 6)) if p else False

    def _relay(self, pid, x, y, t):
        p = self.doc.part(pid)
        if p is None:
            return
        on = self._relay_on(pid, t)
        if p.kind == "RELAY2":
            self._relay2(x, y, on)
            return
        box = [(x - 80, y - 50), (x + 80, y + 50)]
        self.c.create_rectangle(*self.flat([box[0], box[1]]), outline=INK, fill="",
                                width=max(1.1, 1.8 * self.s))
        self.c.create_rectangle(*self.flat([(x - 68, y - 30), (x - 38, y + 30)]),
                                outline=INK, fill="", width=max(1.0, 1.4 * self.s))
        for k in range(1, 5):
            yy = y - 30 + k * 12
            self.line([(x - 64, yy), (x - 42, yy)], width=0.9)
        X, Y = self.T(x - 53, y)
        self.c.create_text(X, Y, text="COIL", angle=90, fill=MUTED,
                           font=(FONT, 7))
        for px, py in ((x + 10, y - 50), (x + 60, y - 50), (x + 80, y)):
            X, Y = self.T(px, py)
            r = 2.6 * self.s
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=INK, outline="")
        self.text(x + 14, y - 38, "COM", anchor="w", size=7)
        self.text(x + 58, y - 38, "NC", anchor="w", size=7)
        self.text(x + 62, y + 10, "NO", anchor="w", size=7)
        self.line([(x + 10, y - 50), (x + 10, y - 18)], width=1.2)
        X, Y = self.T(x + 10, y - 18)
        r = 2.2 * self.s
        self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=INK, outline="")
        arm = (x + 55, y - 50) if not on else (x + 78, y)
        self.line([(x + 10, y - 18), arm], width=2.0)

    def _relay2(self, x, y, on):
        self.c.create_rectangle(*self.flat([(x - 100, y - 80), (x + 100, y + 80)]),
                                outline=INK, fill="", width=max(1.1, 1.8 * self.s))
        self.c.create_rectangle(*self.flat([(x - 90, y - 30), (x - 50, y + 30)]),
                                outline=INK, fill="", width=max(1.0, 1.4 * self.s))
        for k in range(1, 5):
            yy = y - 30 + k * 12
            self.line([(x - 86, yy), (x - 54, yy)], width=0.9)
        X, Y = self.T(x - 70, y)
        self.c.create_text(X, Y, text="COIL", angle=90, fill=MUTED,
                           font=(FONT, 7))
        for px, py in ((x - 30, y - 80), (x + 20, y - 80), (x + 100, y - 40),
                       (x - 30, y + 80), (x + 20, y + 80), (x + 100, y + 40)):
            X, Y = self.T(px, py)
            r = 2.6 * self.s
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=INK, outline="")
        self.text(x - 26, y - 68, "COM1", anchor="w", size=6)
        self.text(x + 12, y - 68, "NC1", anchor="w", size=6)
        self.text(x + 88, y - 44, "NO1", anchor="e", size=6)
        self.text(x - 26, y + 62, "COM2", anchor="w", size=6)
        self.text(x + 12, y + 62, "NC2", anchor="w", size=6)
        self.text(x + 88, y + 36, "NO2", anchor="e", size=6)
        for py, pivot, nc, no in ((y - 80, y - 24, (x + 20, y - 80), (x + 100, y - 40)),
                                  (y + 80, y + 24, (x + 20, y + 80), (x + 100, y + 40))):
            self.line([(x - 30, py), (x - 30, pivot)], width=1.1)
            X, Y = self.T(x - 30, pivot)
            r = 2.2 * self.s
            self.c.create_oval(X - r, Y - r, X + r, Y + r, fill=INK, outline="")
            arm = nc if not on else no
            self.line([(x - 30, pivot), arm], width=2.0)

    def _burn(self, x, y):
        X, Y = self.T(x, y)
        r = 15 * self.s
        self.c.create_oval(X - r, Y - r, X + r, Y + r, fill="#3f1a1a", outline="")
        d = r * 0.72
        self.c.create_line(X - d, Y - d, X + d, Y + d, fill="#fca5a5",
                           width=max(1.2, 2.0 * self.s))
        self.c.create_line(X - d, Y + d, X + d, Y - d, fill="#fca5a5",
                           width=max(1.2, 2.0 * self.s))
