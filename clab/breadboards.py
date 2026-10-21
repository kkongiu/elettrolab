import math
import re

COLS = 30
ROWS = "ABCDEFGHIJ"
COL_X = {c: 100 + (c - 1) * 24 for c in range(1, COLS + 1)}
ROW_Y = {"A": 120, "B": 142, "C": 164, "D": 186, "E": 208,
         "F": 250, "G": 272, "H": 294, "I": 316, "J": 338}
RAIL_Y = {"T+": 62, "T-": 84, "B+": 360, "B-": 382}
RAIL_COLORS = {"T+": "#c92a2a", "T-": "#1864ab", "B+": "#c92a2a", "B-": "#1864ab"}
BOARD = (40, 30, 860, 400)
W, H = 900, 420

HOLE_RE = re.compile(r"^(T\+|T-|B\+|B-|[A-J])(\d{1,2})$")


def parse_hole(name):
    m = HOLE_RE.fullmatch(str(name))
    if not m:
        raise ValueError(f"foro non valido: {name!r}")
    kind, col = m.group(1), int(m.group(2))
    if not 1 <= col <= COLS:
        raise ValueError(f"colonna fuori range: {name!r}")
    return kind, col


def hole_xy(name):
    kind, col = parse_hole(name)
    x = COL_X[col]
    y = RAIL_Y[kind] if kind in RAIL_Y else ROW_Y[kind]
    return (x, y)


def all_holes():
    out = []
    for row in ROWS:
        for col in range(1, COLS + 1):
            out.append(f"{row}{col}")
    for rail in RAIL_Y:
        for col in range(1, COLS + 1):
            out.append(f"{rail}{col}")
    return out


class UF:
    def __init__(self, names):
        self.p = {n: n for n in names}

    def find(self, a):
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _board_connections(uf):
    for col in range(1, COLS + 1):
        for group in ("ABCDE", "FGHIJ"):
            base = f"{group[0]}{col}"
            for row in group[1:]:
                uf.union(base, f"{row}{col}")
    for rail in RAIL_Y:
        base = f"{rail}1"
        for col in range(2, COLS + 1):
            uf.union(base, f"{rail}{col}")


def validate_layout(doc, layout):
    if not layout:
        return [{"code": "no_layout", "message": "breadboard non disponibile"}]
    errors = []
    holes = set(all_holes())
    uf = UF(holes)
    _board_connections(uf)
    try:
        for wire in layout.get("wires", []):
            pts = wire.get("points", [])
            for a, b in zip(pts, pts[1:]):
                if a not in holes or b not in holes:
                    errors.append({"code": "bad_hole", "message": f"foro inesistente: {a} / {b}"})
                    continue
                uf.union(a, b)
    except Exception as e:
        return [{"code": "invalid", "message": str(e)}]

    pin_holes = {}
    for pid in doc.parts:
        p = doc.part(pid)
        if p is None:
            continue
        lp = layout.get("parts", {}).get(pid)
        if not lp:
            errors.append({"code": "no_part", "part": pid,
                           "message": f"{pid}: manca nella breadboard"})
            continue
        for pin in p.spec.pins:
            hole = lp.get("pins", {}).get(pin)
            if hole is None:
                if pin in p.spec.optional:
                    continue
                errors.append({"code": "no_pin", "part": pid, "pin": pin,
                               "message": f"{pid}.{pin}: pin non posizionato"})
                continue
            if hole not in holes:
                errors.append({"code": "bad_hole", "part": pid, "pin": pin,
                               "message": f"{pid}.{pin}: foro inesistente {hole}"})
                continue
            pin_holes[(pid, pin)] = hole
    for pid in layout.get("parts", {}):
        if pid not in doc.parts:
            errors.append({"code": "extra_part", "part": pid,
                           "message": f"{pid}: presente solo nella breadboard"})

    net_holes = {}
    for net, refs in doc.nets.items():
        for ref in refs:
            pid, pin = ref.rsplit(".", 1)
            hole = pin_holes.get((pid, pin))
            if hole:
                net_holes.setdefault(net, []).append(hole)
    for net, hs in net_holes.items():
        roots = {uf.find(h) for h in hs}
        if len(roots) > 1:
            errors.append({"code": "open_net", "net": net,
                           "message": f"rete {net}: pin non collegati sulla breadboard"})
    nets = list(net_holes)
    for i in range(len(nets)):
        for j in range(i + 1, len(nets)):
            a, b = nets[i], nets[j]
            if any(uf.find(x) == uf.find(y) for x in net_holes[a] for y in net_holes[b]):
                errors.append({"code": "short", "net": a,
                               "message": f"corto tra {a} e {b} sulla breadboard"})
    return errors


class LayoutError(Exception):
    pass


def _offsets(n):
    if n <= 1:
        return [0]
    if n == 2:
        return [0, 2]
    if n == 3:
        return [0, 2, 4]
    if n == 5:
        return [0, 2, 4, 6, 8]
    return list(range(n))


def _is_rail_hole(name):
    return name.startswith(("T+", "T-", "B+", "B-"))


def generate(doc, spread=True):
    layout = {"parts": {}, "wires": []}
    gnd = doc.ground
    sources = sorted(pid for pid in doc.parts if doc.part(pid) is not None and doc.part(pid).kind == "V")
    primary = sources[0] if sources else None
    pos_net = doc.net_of(primary, "+") if primary else None
    primary_rails = (primary is not None and doc.net_of(primary, "+") == pos_net
                     and doc.net_of(primary, "-") == gnd)

    rail_col = {"T+": 1, "T-": 1}

    def rail_hole(net):
        rail = "T-" if net == gnd else "T+"
        col = rail_col[rail]
        if col > COLS:
            raise LayoutError(f"rail {rail} pieno")
        rail_col[rail] = col + 1
        return f"{rail}{col}"

    vpos = 0
    pending = []
    for pid in sorted(doc.parts):
        p = doc.part(pid)
        if p is None:
            continue
        if p.kind == "GND":
            pin = p.spec.pins[0]
            layout["parts"][pid] = {"pins": {pin: rail_hole(gnd)}}
            continue
        if p.kind == "V" and pid == primary and primary_rails:
            pins = {pin: rail_hole(doc.net_of(pid, pin)) for pin in p.spec.pins}
            layout["parts"][pid] = {"pins": pins, "pos": (4, 130 + 80 * vpos)}
            vpos += 1
            continue
        pending.append(pid)

    used = {0: set(), 1: set()}
    centers = []

    def place(p):
        offs = _offsets(len(p.spec.pins))
        span = max(offs) + 1
        best = None
        for row in ROWS:
            group = 0 if row in "ABCDE" else 1
            for c0 in range(1, COLS - span + 2):
                cols = [c0 + offs[i] for i in range(len(p.spec.pins))]
                if any(col in used[group] for col in cols):
                    continue
                xs = [COL_X[c] for c in cols]
                cx, cy = sum(xs) / len(xs), ROW_Y[row]
                score = (min(math.hypot(cx - x, cy - y) for x, y in centers)
                         if centers else 0.0)
                key = (score, -ROWS.index(row), -c0)
                if best is None or key > best[0]:
                    best = (key, row, c0, cols, cx, cy)
        return best, offs

    pending.sort(key=lambda pid: (-(max(_offsets(len(doc.part(pid).spec.pins))) + 1), pid))
    for pid in pending:
        p = doc.part(pid)
        best, offs = place(p)
        if best is None:
            raise LayoutError(f"breadboard piena: {pid}")
        _, row, c0, cols, cx, cy = best
        pins = {pin: f"{row}{c0 + offs[i]}" for i, pin in enumerate(p.spec.pins)}
        entry = {"pins": pins}
        if p.kind == "V":
            entry["pos"] = (4, 130 + 80 * vpos)
            vpos += 1
        layout["parts"][pid] = entry
        group = 0 if row in "ABCDE" else 1
        for col in cols:
            used[group].add(col)
        centers.append((cx, cy))

    route_wires(doc, layout, pos_net=pos_net, gnd=gnd)
    return layout


def _positive_net(doc):
    sources = sorted(pid for pid in doc.parts
                     if doc.part(pid) is not None and doc.part(pid).kind == "V")
    if not sources:
        return None
    return doc.net_of(sources[0], "+")


def route_wires(doc, layout, pos_net=None, gnd=None):
    gnd = gnd if gnd is not None else doc.ground
    pos_net = pos_net if pos_net is not None else _positive_net(doc)
    layout["wires"] = []
    bottom_used = {gnd: False, pos_net: False}

    def hole_col(hole):
        return int(HOLE_RE.fullmatch(hole).group(2))

    for net, refs in doc.nets.items():
        holes = []
        for ref in refs:
            pid, pin = ref.rsplit(".", 1)
            hole = layout.get("parts", {}).get(pid, {}).get("pins", {}).get(pin)
            if hole:
                holes.append(hole)
        if net == gnd or net == pos_net:
            top = "T-" if net == gnd else "T+"
            bottom = "B-" if net == gnd else "B+"
            for hole in holes:
                if _is_rail_hole(hole):
                    continue
                kind, col = parse_hole(hole)
                if kind in "FGHIJ":
                    rail = bottom
                    bottom_used[net] = True
                else:
                    rail = top
                layout["wires"].append({"net": net,
                                        "points": [hole, f"{rail}{col}"]})
        elif len(holes) >= 2:
            hub = holes[0]
            for hole in holes[1:]:
                layout["wires"].append({"net": net, "points": [hub, hole]})
    if bottom_used.get(gnd):
        layout["wires"].append({"net": gnd, "points": ["T-1", "B-1"]})
    if pos_net is not None and bottom_used.get(pos_net):
        layout["wires"].append({"net": pos_net, "points": ["T+1", "B+1"]})
    return layout


def reroute(doc, layout):
    return route_wires(doc, layout)


def shift_part(doc, layout, pid, dcol, drow):
    if pid not in layout.get("parts", {}):
        return False, "componente assente"
    pins = layout["parts"][pid].get("pins", {})
    used = set()
    for other, entry in layout.get("parts", {}).items():
        if other != pid:
            used.update(entry.get("pins", {}).values())
    new = {}
    for pin, hole in pins.items():
        kind, col = parse_hole(hole)
        if kind in RAIL_Y:
            return False, "i pin sul rail non si spostano"
        row = ROWS.index(kind)
        nr, nc = row + drow, col + dcol
        if nr < 0 or nr >= len(ROWS) or nc < 1 or nc > COLS:
            return False, "fuori dalla breadboard"
        target = f"{ROWS[nr]}{nc}"
        if target in used or target in new.values():
            return False, "foro occupato"
        new[pin] = target
    layout["parts"][pid]["pins"] = new
    return True, ""


def rotate_part(doc, layout, pid):
    if pid not in layout.get("parts", {}):
        return False, "componente assente"
    entry = layout["parts"][pid]
    pins = entry.get("pins", {})
    if len(pins) < 2:
        return False, "componente non ruotabile"
    values = list(pins.values())
    keys = list(pins.keys())
    for key, hole in zip(keys, reversed(values)):
        pins[key] = hole
    return True, ""
