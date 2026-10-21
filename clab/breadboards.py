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
    for pid, p in doc.parts.items():
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


BREADBOARDS = {
    "exp03": {
        "parts": {
            "V1": {"pins": {"+": "T+1", "-": "T-1"}, "pos": (4, 200)},
            "R1": {"pins": {"1": "A5", "2": "A10"}},
            "D1": {"pins": {"A": "A14", "K": "A16"}},
        },
        "wires": [
            {"net": "p", "points": ["T+5", "A5"]},
            {"net": "m", "points": ["A10", "A14"]},
            {"net": "gnd", "points": ["T-16", "A16"]},
        ],
    },
    "exp06": {
        "parts": {
            "V1": {"pins": {"+": "T+1", "-": "T-1"}, "pos": (4, 200)},
            "SW1": {"pins": {"1": "A4", "2": "A7"}},
            "R1": {"pins": {"1": "A10", "2": "A14"}},
            "D1": {"pins": {"A": "A17", "K": "A19"}},
        },
        "wires": [
            {"net": "p", "points": ["T+4", "A4"]},
            {"net": "s", "points": ["A7", "A10"]},
            {"net": "m", "points": ["A14", "A17"]},
            {"net": "gnd", "points": ["T-19", "A19"]},
        ],
    },
    "exp09": {
        "parts": {
            "V1": {"pins": {"+": "T+1", "-": "T-1"}, "pos": (4, 200)},
            "SW1": {"pins": {"1": "A4", "2": "A7"}},
            "R1": {"pins": {"1": "A10", "2": "A16"}},
            "C1": {"pins": {"+": "A19", "-": "A21"}},
        },
        "wires": [
            {"net": "p", "points": ["T+4", "A4"]},
            {"net": "a", "points": ["A7", "A10"]},
            {"net": "m", "points": ["A16", "A19"]},
            {"net": "gnd", "points": ["T-21", "A21"]},
        ],
    },
    "exp13": {
        "parts": {
            "V1": {"pins": {"+": "T+1", "-": "T-1"}, "pos": (4, 200)},
            "D1": {"pins": {"A": "A6", "K": "A8"}},
        },
        "wires": [
            {"net": "p", "points": ["T+6", "A6"]},
            {"net": "gnd", "points": ["T-8", "A8"]},
        ],
    },
}
