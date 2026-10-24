import json
from pathlib import Path

from .units import fmt

ROOT = Path(__file__).resolve().parent.parent
FP_DIR = ROOT / "data" / "footprints"

MARGIN = 4.0
GAP = 5.0
TRACE_W = 0.6

DEFAULT = {
    "R": "R_axial", "C": "C_radial", "L": "L_axial",
    "LED": "LED_5mm", "D": "DO41", "V": "TERM_2",
    "SW": "SW_2", "POT": "POT_3", "RELAY": "RELAY_1P",
    "RELAY2": "RELAY_2P", "NPN": "TO92_NPN", "PUT": "TO92_PUT",
    "MOS": "TO92_MOS", "SPK": "TERM_2", "LAMP": "LAMP_2",
    "GND": "WIRE_1", "XFMR": "XFMR_4",
}
COMPONENT = {
    "lm2596": "TO220_3",
    "solar_charger": "TO220_3",
    "switch_pwm": "TO220_4",
}


class PcbError(Exception):
    pass


class Footprint:
    def __init__(self, data):
        self.id = data["id"]
        self.pads = {k: (float(v[0]), float(v[1])) for k, v in data["pads"].items()}
        pad = data.get("pad", {})
        self.pad_d = float(pad.get("diameter", 2.0))
        self.drill = float(pad.get("drill", 0.9))
        self.body = data.get("body", {"type": "rect", "w": 8.0, "h": 4.0})
        self.silk = data.get("silk", [])

    def bbox(self):
        xs = [p[0] for p in self.pads.values()]
        ys = [p[1] for p in self.pads.values()]
        r = self.pad_d / 2
        x0, x1 = min(xs) - r, max(xs) + r
        y0, y1 = min(ys) - r, max(ys) + r
        b = self.body
        if b.get("type") == "rect":
            x0, x1 = min(x0, -b["w"] / 2), max(x1, b["w"] / 2)
            y0, y1 = min(y0, -b["h"] / 2), max(y1, b["h"] / 2)
        elif b.get("type") == "circle":
            x0, x1 = min(x0, -b["d"] / 2), max(x1, b["d"] / 2)
            y0, y1 = min(y0, -b["d"] / 2), max(y1, b["d"] / 2)
        return (x0, y0, x1, y1)


def load_footprints():
    out = {}
    if not FP_DIR.exists():
        return out
    for path in sorted(FP_DIR.glob("*.json")):
        fp = Footprint(json.loads(path.read_text(encoding="utf-8")))
        out[fp.id] = fp
    return out


def footprint_id(part):
    if part.get("footprint"):
        return part.get("footprint")
    if part.type in COMPONENT:
        return COMPONENT[part.type]
    return DEFAULT.get(part.kind)


class PcbLayout:
    def __init__(self, doc):
        self.doc = doc
        self.fps = load_footprints()
        self.parts = {}
        self.traces = []
        self.silk = []
        self._place()
        self._route()
        self._silk()

    def _place(self):
        MAX_W = 90.0
        ROW_GAP = 6.0
        rows = {}
        self.parts = {}
        row_parts = []
        row_index = 0
        row_top = 0.0
        row_h = 0.0
        cursor = 0.0

        def close_row():
            nonlocal row_parts, row_index, row_top, row_h, cursor
            if not row_parts:
                return
            for e in row_parts:
                e["row"] = row_index
                self.parts[e["pid"]] = e
            rows[row_index] = row_parts
            row_index += 1
            row_top += row_h + ROW_GAP
            row_parts = []
            row_h = 0.0
            cursor = 0.0

        for pid in self.doc.parts:
            p = self.doc.part(pid)
            fid = footprint_id(p)
            fp = self.fps.get(fid) if fid else None
            if fp is None:
                raise PcbError(f"{pid}: footprint non disponibile ({p.kind})")
            missing = [pin for pin in p.spec.pins if pin not in fp.pads]
            if missing:
                raise PcbError(f"{pid}: pin senza pad in {fid}: {', '.join(missing)}")
            x0, y0, x1, y1 = fp.bbox()
            w, h = x1 - x0, y1 - y0
            if row_parts and cursor + w > MAX_W:
                close_row()
            x = cursor - x0
            y = row_top - y0
            pads = {pin: (x + pad[0], y + pad[1]) for pin, pad in fp.pads.items()}
            row_parts.append({"pid": pid, "fp": fp, "x": x, "y": y, "pads": pads})
            cursor = x + w + GAP
            row_h = max(row_h, h)
        close_row()
        if not self.parts:
            raise PcbError("nessun componente con footprint")
        xs, ys = [], []
        for e in self.parts.values():
            x0, y0, x1, y1 = e["fp"].bbox()
            xs += [e["x"] + x0, e["x"] + x1]
            ys += [e["y"] + y0, e["y"] + y1]
        dx = MARGIN - min(xs)
        dy = MARGIN - min(ys)
        for e in self.parts.values():
            e["x"] += dx
            e["y"] += dy
            e["pads"] = {pin: (p[0] + dx, p[1] + dy) for pin, p in e["pads"].items()}
        self.rows = rows
        self.board = (max(xs) - min(xs) + 2 * MARGIN, max(ys) - min(ys) + 2 * MARGIN)

    def _route(self):
        ROW_GAP = 6.0
        gnd = self.doc.ground
        bounds = {}
        for e in self.parts.values():
            r = e["row"]
            x0, y0, x1, y1 = e["fp"].bbox()
            top, bot = e["y"] + y0, e["y"] + y1
            if r in bounds:
                bounds[r][0] = min(bounds[r][0], top)
                bounds[r][1] = max(bounds[r][1], bot)
            else:
                bounds[r] = [top, bot]
        edge_x = self.board[0] - MARGIN / 2
        bus_y = {r: v[1] + ROW_GAP / 2 for r, v in bounds.items()}
        gnd_by_row = {}
        for net, refs in self.doc.nets.items():
            pts = []
            for ref in refs:
                pid, pin = ref.rsplit(".", 1)
                e = self.parts.get(pid)
                if e and pin in e["pads"]:
                    pts.append((e["pads"][pin], e["row"]))
            if net == gnd:
                for (x, y), r in pts:
                    gnd_by_row.setdefault(r, []).append((x, y))
            elif len(pts) >= 2:
                pts = sorted(pts, key=lambda t: t[0][0])
                for (a, _), (b, _) in zip(pts, pts[1:]):
                    if abs(a[1] - b[1]) < 1e-6:
                        self.traces.append({"net": net, "points": [a, b]})
                    else:
                        self.traces.append({"net": net, "points": [a, (b[0], a[1]), b]})
        for r, pads in gnd_by_row.items():
            by = bus_y[r]
            xs = [x for x, y in pads]
            self.traces.append({"net": gnd, "points": [(min(xs), by), (edge_x, by)]})
            for x, y in pads:
                self.traces.append({"net": gnd, "points": [(x, y), (x, by)]})
        if len(bus_y) > 1:
            ys = sorted(bus_y.values())
            self.traces.append({"net": gnd, "points": [(edge_x, ys[0]), (edge_x, ys[-1])]})

    def _label(self, pid):
        p = self.doc.part(pid)
        k = p.kind
        if k == "R":
            return f"{pid} {fmt(p.num('r'), '\u03a9')}"
        if k == "C":
            c = p.num("c")
            if c < 1e-6:
                return f"{pid} {c * 1e9:g} nF"
            if c <= 1e-3:
                return f"{pid} {c * 1e6:g} \u00b5F"
            return f"{pid} {c * 1e3:g} mF"
        if k == "L":
            return f"{pid} {fmt(p.num('l'), 'H')}"
        if k == "V":
            return f"{pid} {fmt(p.num('v'), 'V')}"
        if k == "LED":
            return f"{pid} LED"
        if k == "D":
            return f"{pid} D"
        if k == "LAMP":
            return f"{pid} {p.num('vn'):g} V {p.num('p'):g} W"
        if k == "SW":
            if p.type == "lm2596":
                return f"{pid} LM2596 5 V"
            if p.type == "solar_charger":
                return f"{pid} CHG 14.4 V"
            return pid
        if k == "POT":
            return f"{pid} {fmt(p.num('rtotal'), '\u03a9')}"
        if k == "XFMR":
            return f"{pid} n={p.num('n'):.3g}"
        if k == "SPK":
            return f"{pid} {fmt(p.num('r'), '\u03a9')}"
        if k in ("NPN", "PUT", "MOS"):
            return f"{pid} {k}"
        if k == "GND":
            return "GND"
        return pid

    def _silk(self):
        for pid, e in self.parts.items():
            fp, x, y = e["fp"], e["x"], e["y"]
            b = fp.body
            if b.get("type") == "rect":
                self.silk.append({"type": "rect", "x": x - b["w"] / 2, "y": y - b["h"] / 2,
                                  "w": b["w"], "h": b["h"]})
                ty = y - b["h"] / 2 - 1.6
            elif b.get("type") == "circle":
                self.silk.append({"type": "circle", "x": x, "y": y, "d": b["d"]})
                ty = y - b["d"] / 2 - 1.6
            else:
                ty = y - 4.0
            self.silk.append({"type": "text", "x": x, "y": ty, "text": self._label(pid), "size": 1.5})
            for s in fp.silk:
                if s.get("type") == "line":
                    self.silk.append({"type": "line",
                                      "points": [(x + px, y + py) for px, py in s["points"]]})
            for pin, (px, py) in e["pads"].items():
                if pin in ("+", "-", "A", "K"):
                    self.silk.append({"type": "text", "x": px, "y": py + 2.6,
                                      "text": pin, "size": 1.2})

    def to_svg(self):
        w, h = self.board
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}mm" height="{h:.2f}mm" '
               f'viewBox="0 0 {w:.2f} {h:.2f}">']
        out.append(f'<rect x="0" y="0" width="{w:.2f}" height="{h:.2f}" fill="#f7f2e6" '
                   f'stroke="#777" stroke-width="0.2"/>')
        out.append(f'<g stroke="#c92a2a" fill="none" stroke-width="{TRACE_W}" stroke-linecap="round">')
        for tr in self.traces:
            pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in tr["points"])
            out.append(f'<polyline points="{pts}"/>')
        out.append('</g>')
        out.append('<g fill="#c92a2a">')
        for e in self.parts.values():
            for x, y in e["pads"].values():
                out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{e["fp"].pad_d / 2:.2f}"/>')
        out.append('</g>')
        out.append('<g fill="#ffffff">')
        for e in self.parts.values():
            for x, y in e["pads"].values():
                out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{e["fp"].drill / 2:.2f}"/>')
        out.append('</g>')
        out.append('<g stroke="#111" fill="none" stroke-width="0.2">')
        for s in self.silk:
            if s["type"] == "rect":
                out.append(f'<rect x="{s["x"]:.2f}" y="{s["y"]:.2f}" width="{s["w"]:.2f}" '
                           f'height="{s["h"]:.2f}"/>')
            elif s["type"] == "circle":
                out.append(f'<circle cx="{s["x"]:.2f}" cy="{s["y"]:.2f}" r="{s["d"] / 2:.2f}"/>')
            elif s["type"] == "line":
                pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in s["points"])
                out.append(f'<polyline points="{pts}"/>')
        out.append('</g>')
        out.append('<g fill="#111" font-family="monospace" text-anchor="middle">')
        for s in self.silk:
            if s["type"] == "text":
                txt = s["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                out.append(f'<text x="{s["x"]:.2f}" y="{s["y"]:.2f}" '
                           f'font-size="{s["size"]:.2f}">{txt}</text>')
        out.append('</g>')
        out.append('</svg>')
        return "\n".join(out)


class Pcb:
    """Tk view of a PcbLayout (board, copper, pads, silkscreen)."""

    def __init__(self, canvas, layout=None, message=None):
        self.c = canvas
        self.layout = layout
        self.message = message
        self.s = 1.0
        self.ox = 0.0
        self.oy = 0.0

    def T(self, x, y):
        return (self.ox + x * self.s, self.oy + y * self.s)

    def line(self, pts, color, width):
        flat = []
        for x, y in pts:
            X, Y = self.T(x, y)
            flat.extend((X, Y))
        self.c.create_line(*flat, fill=color, width=max(1.0, width * self.s),
                           capstyle="round")

    def text(self, x, y, txt, size=1.5):
        self.c.create_text(*self.T(x, y), text=txt, fill="#111",
                           font=("DejaVu Sans", max(7, min(14, int(size * self.s)))))

    def draw(self):
        c = self.c
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 120 or h < 80:
            w, h = 800, 300
        if self.layout is None:
            c.create_text(w / 2, h / 2, text=self.message or "PCB non disponibile",
                          fill="#6b7280", font=("DejaVu Sans", 10))
            return
        bw, bh = self.layout.board
        self.s = min((w - 24) / bw, (h - 24) / bh)
        self.ox = (w - bw * self.s) / 2
        self.oy = (h - bh * self.s) / 2
        c.create_rectangle(*self.T(0, 0), *self.T(bw, bh), fill="#f7f2e6", outline="#777")
        for tr in self.layout.traces:
            self.line(tr["points"], "#c92a2a", TRACE_W)
        for e in self.layout.parts.values():
            for x, y in e["pads"].values():
                r = e["fp"].pad_d / 2
                c.create_oval(*self.T(x - r, y - r), *self.T(x + r, y + r),
                              fill="#c92a2a", outline="")
        for e in self.layout.parts.values():
            for x, y in e["pads"].values():
                r = e["fp"].drill / 2
                c.create_oval(*self.T(x - r, y - r), *self.T(x + r, y + r),
                              fill="#ffffff", outline="#333")
        for s in self.layout.silk:
            if s["type"] == "rect":
                c.create_rectangle(*self.T(s["x"], s["y"]),
                                   *self.T(s["x"] + s["w"], s["y"] + s["h"]),
                                   outline="#111", fill="")
            elif s["type"] == "circle":
                r = s["d"] / 2
                c.create_oval(*self.T(s["x"] - r, s["y"] - r),
                              *self.T(s["x"] + r, s["y"] + r), outline="#111", fill="")
            elif s["type"] == "line":
                self.line(s["points"], "#111", 0.2)
        for s in self.layout.silk:
            if s["type"] == "text":
                self.text(s["x"], s["y"], s["text"], s["size"])
