import heapq
import json
import math
from pathlib import Path

from .units import fmt

ROOT = Path(__file__).resolve().parent.parent
FP_DIR = ROOT / "data" / "footprints"

MARGIN = 4.0
GAP = 8.0
TRACE_W = 0.3
CELL = 0.5
CLEARANCE = 0.15

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
    "bq24074": "BQ24074_VQFN16",
    "tps61023": "TPS61023_SOT563",
    "tps2553": "TPS2553_SOT23_6",
    "usb_vbus_tvs": "SOD323_2",
    "usb_esd_array": "USB_ESD_4P_GENERIC",
    "protection_liion_1s": "PCM_4PAD_GENERIC",
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
        self.pad_shapes = data.get("pad_shapes", {})
        self.pad_map = {str(k): str(v) for k, v in data.get("pad_map", {}).items()}
        self.body = data.get("body", {"type": "rect", "w": 8.0, "h": 4.0})
        self.silk = data.get("silk", [])

    def bbox(self):
        bounds = []
        for pin, (x, y) in self.pads.items():
            w, h = self.pad_size(pin)
            bounds.append((x - w / 2, y - h / 2, x + w / 2, y + h / 2))
        x0, y0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
        x1, y1 = max(b[2] for b in bounds), max(b[3] for b in bounds)
        b = self.body
        if b.get("type") == "rect":
            x0, x1 = min(x0, -b["w"] / 2), max(x1, b["w"] / 2)
            y0, y1 = min(y0, -b["h"] / 2), max(y1, b["h"] / 2)
        elif b.get("type") == "circle":
            x0, x1 = min(x0, -b["d"] / 2), max(x1, b["d"] / 2)
            y0, y1 = min(y0, -b["d"] / 2), max(y1, b["d"] / 2)
        return (x0, y0, x1, y1)

    def pad_size(self, pin):
        shape = self.pad_shapes.get(pin, {})
        if shape.get("shape") == "rect":
            return float(shape["w"]), float(shape["h"])
        d = float(shape.get("diameter", self.pad_d))
        return d, d

    def pad_drill(self, pin):
        shape = self.pad_shapes.get(pin, {})
        if shape.get("shape") == "rect" or shape.get("drill") == 0:
            return 0.0
        return float(shape.get("drill", self.drill))

    def pad_radius(self, pin):
        if self.pad_shapes.get(pin, {}).get("shape") != "rect":
            return self.pad_size(pin)[0] / 2
        w, h = self.pad_size(pin)
        return math.hypot(w, h) / 2

    def net_pin(self, footprint_pad):
        return self.pad_map.get(str(footprint_pad), str(footprint_pad))


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
    if part.spec.footprint:
        return part.spec.footprint
    if part.type in COMPONENT:
        return COMPONENT[part.type]
    return DEFAULT.get(part.kind)


def _pt_seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    if L <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _seg_dist(a, b, c, d):
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1 = cross(c, d, a)
    d2 = cross(c, d, b)
    d3 = cross(a, b, c)
    d4 = cross(a, b, d)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return 0.0
    return min(_pt_seg_dist(a[0], a[1], c, d), _pt_seg_dist(b[0], b[1], c, d),
               _pt_seg_dist(c[0], c[1], a, b), _pt_seg_dist(d[0], d[1], a, b))


def _seg_rect_dist(a, b, x0, y0, x1, y1):
    if (min(a[0], b[0]) <= x1 and max(a[0], b[0]) >= x0 and
            min(a[1], b[1]) <= y1 and max(a[1], b[1]) >= y0):
        edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                 ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
        if x0 <= a[0] <= x1 and y0 <= a[1] <= y1:
            return 0.0
        if x0 <= b[0] <= x1 and y0 <= b[1] <= y1:
            return 0.0
        d = min(_seg_dist(a, b, c, d) for c, d in edges)
        if d == 0.0:
            return 0.0
        return d
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    endpoint_dist = []
    for x, y in (a, b):
        dx = max(x0 - x, 0.0, x - x1)
        dy = max(y0 - y, 0.0, y - y1)
        endpoint_dist.append(math.hypot(dx, dy))
    return min(min(_pt_seg_dist(x, y, a, b) for x, y in corners), *endpoint_dist)


class PcbLayout:
    def __init__(self, doc):
        self.doc = doc
        self.fps = load_footprints()
        self.parts = {}
        self.traces = []
        self.silk = []
        self.violations = []
        self.warnings = []
        self._place()
        self._route()
        self._silk()

    def _place(self):
        MAX_W = 100.0
        ROW_GAP = 9.0
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
            if p.get("simulation_only", False):
                continue
            fid = footprint_id(p)
            fp = self.fps.get(fid) if fid else None
            if fp is None:
                raise PcbError(f"{pid}: footprint non disponibile ({p.kind})")
            mapped = {fp.net_pin(pin) for pin in fp.pads}
            missing = [pin for pin in p.spec.pins if pin not in mapped]
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

    def _free(self, owner, cell, nid):
        j, i = cell[1], cell[0]
        return all(x == nid for x in owner[j][i])

    def _mark_circle(self, owner, x, y, r, nid, W, H):
        x0 = max(0, int((x - r) / CELL))
        x1 = min(W - 1, int((x + r) / CELL) + 1)
        y0 = max(0, int((y - r) / CELL))
        y1 = min(H - 1, int((y + r) / CELL) + 1)
        for j in range(y0, y1 + 1):
            for i in range(x0, x1 + 1):
                cx, cy = (i + 0.5) * CELL, (j + 0.5) * CELL
                if math.hypot(cx - x, cy - y) <= r:
                    owner[j][i].add(nid)

    def _mark_pad(self, owner, x, y, hw, hh, nid, W, H):
        cell = self.cell
        extra = CLEARANCE + TRACE_W / 2 + cell / 2
        x0 = max(0, int((x - hw - extra) / cell))
        x1 = min(W - 1, int((x + hw + extra) / cell) + 1)
        y0 = max(0, int((y - hh - extra) / cell))
        y1 = min(H - 1, int((y + hh + extra) / cell) + 1)
        for j in range(y0, y1 + 1):
            for i in range(x0, x1 + 1):
                cx, cy = (i + 0.5) * cell, (j + 0.5) * cell
                dx = max(0.0, abs(cx - x) - hw)
                dy = max(0.0, abs(cy - y) - hh)
                if math.hypot(dx, dy) <= extra:
                    owner[j][i].add(nid)

    def _mark_polyline(self, owner, pts, nid, W, H):
        cell = self.cell
        rad = TRACE_W / 2 + CLEARANCE + cell / 2
        for a, b in zip(pts, pts[1:]):
            x0 = max(0, int((min(a[0], b[0]) - rad) / cell))
            x1 = min(W - 1, int((max(a[0], b[0]) + rad) / cell) + 1)
            y0 = max(0, int((min(a[1], b[1]) - rad) / cell))
            y1 = min(H - 1, int((max(a[1], b[1]) + rad) / cell) + 1)
            for j in range(y0, y1 + 1):
                for i in range(x0, x1 + 1):
                    cx, cy = (i + 0.5) * cell, (j + 0.5) * cell
                    if _pt_seg_dist(cx, cy, a, b) <= rad:
                        owner[j][i].add(nid)

    def _astar(self, owner, x0, y0, x1, y1, nid, W, H):
        cell = self.cell
        start = (max(0, min(W - 1, int(x0 / cell))), max(0, min(H - 1, int(y0 / cell))))
        goal = (max(0, min(W - 1, int(x1 / cell))), max(0, min(H - 1, int(y1 / cell))))
        if not self._free(owner, start, nid) or not self._free(owner, goal, nid):
            return None
        open_ = [(0, start)]
        g = {start: 0}
        parent = {}
        while open_:
            _, cur = heapq.heappop(open_)
            if cur == goal:
                path = [cur]
                while path[-1] in parent:
                    path.append(parent[path[-1]])
                path.reverse()
                return [((i + 0.5) * cell, (j + 0.5) * cell) for i, j in path]
            ci, cj = cur
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)):
                ni, nj = ci + di, cj + dj
                if not (0 <= ni < W and 0 <= nj < H):
                    continue
                if di and dj and (not self._free(owner, (ci + di, cj), nid)
                                  or not self._free(owner, (ci, cj + dj), nid)):
                    continue
                nxt = (ni, nj)
                if not self._free(owner, nxt, nid):
                    continue
                ng = g[cur] + 1
                if ng < g.get(nxt, 1e18):
                    g[nxt] = ng
                    parent[nxt] = cur
                    h = max(abs(ni - goal[0]), abs(nj - goal[1]))
                    heapq.heappush(open_, (ng + h, nxt))
        return None

    @staticmethod
    def _smooth(pts):
        out = []
        for p in pts:
            if out and abs(p[0] - out[-1][0]) < 1e-9 and abs(p[1] - out[-1][1]) < 1e-9:
                continue
            while len(out) >= 2:
                a, b = out[-2], out[-1]
                h1 = abs(a[1] - b[1]) < 1e-9 and abs(b[1] - p[1]) < 1e-9
                v1 = abs(a[0] - b[0]) < 1e-9 and abs(b[0] - p[0]) < 1e-9
                if h1 or v1:
                    out.pop()
                else:
                    break
            out.append(p)
        return out

    def _route(self):
        self.traces = []
        self.violations = []
        self.warnings = []
        has_smd = any(e["fp"].pad_shapes for e in self.parts.values())
        self.cell = 0.25 if has_smd else CELL
        bw, bh = self.board
        W = int(math.ceil(bw / self.cell)) + 1
        H = int(math.ceil(bh / self.cell)) + 1
        owner = [[set() for _ in range(W)] for _ in range(H)]
        gnd = self.doc.ground
        pads = []
        by_net = {}
        gnd_pads = []
        uid = 0
        for pid in self.parts:
            e = self.parts[pid]
            for pin, (x, y) in e["pads"].items():
                logical_pin = e["fp"].net_pin(pin)
                net = self.doc.net_of(pid, logical_pin)
                if net is None:
                    net = f"~{uid}"
                    uid += 1
                pad_w, pad_h = e["fp"].pad_size(pin)
                hw, hh = pad_w / 2, pad_h / 2
                pads.append((x, y, hw, hh, net))
                if not net.startswith("~"):
                    by_net.setdefault(net, []).append((x, y, hw, hh))
                if net == gnd:
                    gnd_pads.append((x, y, e["row"]))
        ids = {}
        for _, _, _, _, net in pads:
            ids.setdefault(net, len(ids))
        for x, y, hw, hh, net in pads:
            self._mark_pad(owner, x, y, hw, hh, ids[net], W, H)
        if gnd_pads and gnd in ids and not has_smd:
            bounds = {}
            for e in self.parts.values():
                row = e["row"]
                x0, y0, x1, y1 = e["fp"].bbox()
                top, bottom = e["y"] + y0, e["y"] + y1
                bounds[row] = (min(bounds.get(row, (top, bottom))[0], top),
                               max(bounds.get(row, (top, bottom))[1], bottom))
            bus_y = {row: bottom + 2.0 for row, (top, bottom) in bounds.items()}
            edge_x = MARGIN / 2
            by_row = {}
            for x, y, row in gnd_pads:
                by_row.setdefault(row, []).append((x, y))
            for row, row_pads in by_row.items():
                yy = bus_y[row]
                points = [(edge_x, yy), (max(x for x, _ in row_pads), yy)]
                self.traces.append({"net": gnd, "points": points})
                self._mark_polyline(owner, points, ids[gnd], W, H)
                for x, y in row_pads:
                    points = [(x, y), (x, yy)]
                    self.traces.append({"net": gnd, "points": points})
                    self._mark_polyline(owner, points, ids[gnd], W, H)
            if len(bus_y) > 1:
                ys = sorted(bus_y.values())
                points = [(edge_x, ys[0]), (edge_x, ys[-1])]
                self.traces.append({"net": gnd, "points": points})
                self._mark_polyline(owner, points, ids[gnd], W, H)
        nets = by_net if has_smd else {net: pins for net, pins in by_net.items() if net != gnd}
        for net in sorted(nets, key=lambda n: (n != gnd, len(by_net[n]), n)):
            lst = by_net[net]
            if len(lst) < 2:
                continue
            hub = min(lst, key=lambda q: sum((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
                                             for p in lst))
            for target in [q for q in lst if q is not hub]:
                path = self._astar(owner, hub[0], hub[1], target[0], target[1],
                                   ids[net], W, H)
                if path is None:
                    pts = self._smooth([(hub[0], hub[1]), (target[0], hub[1]),
                                        (target[0], target[1])])
                    if not self._clear(pts, net, pads):
                        self.warnings.append(f"rete {net}: non instradata (spazio insufficiente)")
                        continue
                else:
                    pts = self._smooth([(hub[0], hub[1])] + path + [(target[0], target[1])])
                self.traces.append({"net": net, "points": pts})
                self._mark_polyline(owner, pts, ids[net], W, H)
        self.pad_list = pads
        self._drc()

    def _clear(self, pts, net, pads):
        for tr in self.traces:
            if tr["net"] == net:
                continue
            for p, q in zip(pts, pts[1:]):
                for r, s in zip(tr["points"], tr["points"][1:]):
                    if _seg_dist(p, q, r, s) < TRACE_W + CLEARANCE - 0.01:
                        return False
        for x, y, hw, hh, pnet in pads:
            if pnet == net:
                continue
            for p, q in zip(pts, pts[1:]):
                if _seg_rect_dist(p, q, x-hw, y-hh, x+hw, y+hh) < CLEARANCE + TRACE_W / 2 - 0.01:
                    return False
        return True

    def _drc(self):
        self.violations = []
        for i, a in enumerate(self.traces):
            for b in self.traces[i + 1:]:
                if a["net"] == b["net"]:
                    continue
                for p, q in zip(a["points"], a["points"][1:]):
                    for r, s in zip(b["points"], b["points"][1:]):
                        d = _seg_dist(p, q, r, s)
                        if d < TRACE_W + CLEARANCE - 0.01:
                            self.violations.append((a["net"], b["net"], "trace-trace", d))
        for tr in self.traces:
            for x, y, hw, hh, net in self.pad_list:
                if net == tr["net"]:
                    continue
                for p, q in zip(tr["points"], tr["points"][1:]):
                    d = _seg_rect_dist(p, q, x-hw, y-hh, x+hw, y+hh)
                    if d < CLEARANCE + TRACE_W / 2 - 0.01:
                        self.violations.append((tr["net"], net, "trace-pad", d))
        for i, a in enumerate(self.pad_list):
            for b in self.pad_list[i + 1:]:
                if a[4] == b[4]:
                    continue
                dx = max(0.0, abs(a[0] - b[0]) - a[2] - b[2])
                dy = max(0.0, abs(a[1] - b[1]) - a[3] - b[3])
                d = math.hypot(dx, dy)
                if d < CLEARANCE - 0.01:
                    self.violations.append((a[4], b[4], "pad-pad", d))

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
            fp = e["fp"]
            for pin, (x, y) in e["pads"].items():
                shape = fp.pad_shapes.get(pin, {})
                if shape.get("shape") == "rect":
                    pw, ph = fp.pad_size(pin)
                    out.append(f'<rect x="{x-pw/2:.2f}" y="{y-ph/2:.2f}" width="{pw:.2f}" height="{ph:.2f}"/>')
                else:
                    out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{fp.pad_size(pin)[0]/2:.2f}"/>')
        out.append('</g>')
        out.append('<g fill="#ffffff">')
        for e in self.parts.values():
            for pin, (x, y) in e["pads"].items():
                drill = e["fp"].pad_drill(pin)
                if drill:
                    out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{drill / 2:.2f}"/>')
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
            for pin, (x, y) in e["pads"].items():
                pw, ph = e["fp"].pad_size(pin)
                if e["fp"].pad_shapes.get(pin, {}).get("shape") == "rect":
                    c.create_rectangle(*self.T(x-pw/2, y-ph/2), *self.T(x+pw/2, y+ph/2),
                                       fill="#c92a2a", outline="")
                else:
                    r = pw / 2
                    c.create_oval(*self.T(x - r, y - r), *self.T(x + r, y + r),
                                  fill="#c92a2a", outline="")
        for e in self.layout.parts.values():
            for pin, (x, y) in e["pads"].items():
                drill = e["fp"].pad_drill(pin)
                if drill:
                    r = drill / 2
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
