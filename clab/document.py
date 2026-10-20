import copy
import json
import re
from pathlib import Path

from .circuit import GROUND, Circuit, CircuitError
from .units import to_float

META_KEYS = ("id", "title", "notes", "ref", "analysis", "tstop", "dt", "expect")
PREFIX = {"R": "R", "V": "V", "LED": "D", "SW": "SW", "C": "C", "L": "L",
          "POT": "POT", "RELAY": "RY", "RELAY2": "RY", "GND": "GND", "NPN": "Q"}


class Document:
    def __init__(self, data, db, layout=None, source=None, builtin=False):
        self.db = db
        self.source = source
        self.builtin = builtin
        self.meta = {k: copy.deepcopy(v) for k, v in data.items()
                     if k not in ("parts", "nets", "layout")}
        self.parts = {pid: dict(pdata) for pid, pdata in data.get("parts", {}).items()}
        self.nets = {name: list(refs) for name, refs in data.get("nets", {}).items()}
        self.layout = self._normalize_layout(layout or data.get("layout"))
        self._cache = {}
        self.selected = None
        self.ensure_layout()

    def _normalize_layout(self, layout):
        layout = copy.deepcopy(layout) if layout else {}
        parts = {}
        for pid, pos in layout.get("parts", {}).items():
            if isinstance(pos, (list, tuple)) and len(pos) == 3:
                parts[pid] = [int(pos[0]), int(pos[1]), int(pos[2]) % 360]
        out = {"parts": parts, "gnd_y": int(layout.get("gnd_y", 330))}
        routes = layout.get("routes")
        if routes:
            out["routes"] = {k: [list(map(tuple, poly)) for poly in v]
                             for k, v in routes.items()}
        return out

    @classmethod
    def from_dict(cls, data, db, layout=None, source=None, builtin=False):
        return cls(data, db, layout=layout, source=source, builtin=builtin)

    @classmethod
    def from_file(cls, circuit_path, layout_path, db, builtin=False):
        data = json.loads(Path(circuit_path).read_text(encoding="utf-8"))
        layout = None
        if layout_path is not None and layout_path.exists():
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
        return cls(data, db, layout=layout, source=circuit_path, builtin=builtin)

    def to_dict(self):
        data = {}
        for k in META_KEYS:
            if k in self.meta:
                data[k] = copy.deepcopy(self.meta[k])
        if "id" not in data:
            data["id"] = "circuito"
        data["parts"] = {pid: copy.deepcopy(p) for pid, p in self.parts.items()}
        data["nets"] = {name: list(refs) for name, refs in self.nets.items()}
        return data

    def to_layout_dict(self):
        out = {"version": 1, "gnd_y": self.layout.get("gnd_y", 330),
               "parts": {pid: list(pos) for pid, pos in self.layout["parts"].items()}}
        if self.layout.get("routes"):
            out["routes"] = {k: [[list(pt) for pt in poly] for poly in v]
                             for k, v in self.layout["routes"].items()}
        return out

    def to_json(self, layout=False):
        obj = self.to_layout_dict() if layout else self.to_dict()
        return json.dumps(obj, indent=2, ensure_ascii=False)

    def to_circuit(self):
        return Circuit(self.to_dict(), self.db)

    def clone(self):
        return Document(copy.deepcopy(self.to_dict()), self.db,
                        layout=copy.deepcopy(self.to_layout_dict()))

    def snapshot(self):
        return (copy.deepcopy(self.parts), copy.deepcopy(self.nets),
                copy.deepcopy(self.layout), copy.deepcopy(self.meta))

    def restore(self, snap):
        self.parts, self.nets, self.layout, self.meta = copy.deepcopy(snap)
        self._cache = {}
        self.ensure_layout()

    def invalidate(self):
        self._cache = {}

    def part(self, pid):
        if pid in self._cache:
            return self._cache[pid]
        data = self.parts.get(pid)
        if not data:
            return None
        spec = self.db.types.get(data.get("type"))
        if spec is None:
            return None
        part = self.db.part(pid, data)
        self._cache[pid] = part
        return part

    def pins(self, pid):
        p = self.part(pid)
        return list(p.spec.pins) if p else []

    def kind(self, pid):
        p = self.part(pid)
        return p.kind if p else None

    def optional(self, pid):
        p = self.part(pid)
        return set(p.spec.optional) if p else set()

    def net_of(self, pid, pin):
        ref = f"{pid}.{pin}"
        for name, refs in self.nets.items():
            if ref in refs:
                return name
        return None

    def connected(self, pid, pin):
        return self.net_of(pid, pin) is not None

    @property
    def ground(self):
        for name in self.nets:
            if name in GROUND:
                return name
        return None

    def _is_ground(self, pid):
        return self.kind(pid) == "GND"

    def _next_id(self, kind):
        pre = PREFIX.get(kind, "X")
        n = 1
        while f"{pre}{n}" in self.parts:
            n += 1
        return f"{pre}{n}"

    def _next_net(self):
        n = 1
        while f"n{n}" in self.nets:
            n += 1
        return f"n{n}"

    def ensure_layout(self):
        self.layout.setdefault("parts", {})
        self.layout.setdefault("gnd_y", 330)
        for pid in list(self.layout["parts"]):
            if pid not in self.parts:
                del self.layout["parts"][pid]
        missing = [pid for pid in self.parts if pid not in self.layout["parts"]]
        for i, pid in enumerate(missing):
            x = 120 + (i % 5) * 150
            y = 90 + (i // 5) * 130
            self.layout["parts"][pid] = [x, y, 0]
        routes = self.layout.get("routes")
        if routes:
            for name in list(routes):
                if name not in self.nets:
                    del routes[name]

    def position(self, pid):
        return self.layout["parts"].get(pid, [0, 0, 0])

    def move(self, pid, x, y):
        pos = self.layout["parts"].setdefault(pid, [0, 0, 0])
        pos[0] = int(x)
        pos[1] = int(y)

    def rotate(self, pid):
        pos = self.layout["parts"].get(pid)
        if not pos:
            return
        if self.kind(pid) in ("POT", "RELAY", "RELAY2", "GND"):
            return
        pos[2] = (pos[2] + 90) % 360

    def add_part(self, typ, x=None, y=None, rot=0):
        spec = self.db.types.get(typ)
        if spec is None:
            raise CircuitError("unknown_type", f"componente sconosciuto: {typ!r}", type=typ)
        pid = self._next_id(spec.kind)
        self.parts[pid] = {"type": typ}
        if x is None:
            x = 140 + (len(self.parts) % 5) * 150
        if y is None:
            y = 100 + (len(self.parts) // 5) * 130
        self.layout["parts"][pid] = [int(x), int(y), int(rot) % 360]
        if spec.kind == "GND":
            pin = spec.pins[0]
            self.nets.setdefault("gnd", [])
            ref = f"{pid}.{pin}"
            if ref not in self.nets["gnd"]:
                self.nets["gnd"].append(ref)
        self.invalidate()
        return pid

    def delete_part(self, pid):
        if pid not in self.parts:
            return
        ref_prefix = f"{pid}."
        for name in list(self.nets):
            self.nets[name] = [r for r in self.nets[name] if not r.startswith(ref_prefix)]
            if not self.nets[name]:
                del self.nets[name]
        del self.parts[pid]
        self.layout["parts"].pop(pid, None)
        if self.selected == pid:
            self.selected = None
        self.invalidate()

    def connect(self, pid1, pin1, pid2, pin2):
        if (pid1, pin1) == (pid2, pin2):
            return self.net_of(pid1, pin1)
        if pin1 not in self.pins(pid1) or pin2 not in self.pins(pid2):
            raise CircuitError("unknown_pin", "pin inesistente", parts=[pid1, pid2])
        ref1, ref2 = f"{pid1}.{pin1}", f"{pid2}.{pin2}"
        n1, n2 = self.net_of(pid1, pin1), self.net_of(pid2, pin2)
        if n1 is not None and n1 == n2:
            return n1
        if self._is_ground(pid1) or self._is_ground(pid2):
            name = "gnd"
            self.nets.setdefault(name, [])
            for net in (n1, n2):
                if net is not None and net != name and net in self.nets:
                    for ref in self.nets.pop(net):
                        if ref not in self.nets[name]:
                            self.nets[name].append(ref)
            for ref in (ref1, ref2):
                if ref not in self.nets[name]:
                    self.nets[name].append(ref)
            self.invalidate()
            return name
        if n1 is None and n2 is None:
            name = self._next_net()
            self.nets[name] = [ref1, ref2]
        elif n1 is None:
            self.nets[n2].append(ref1)
            name = n2
        elif n2 is None:
            self.nets[n1].append(ref2)
            name = n1
        else:
            for ref in self.nets.pop(n2):
                if ref not in self.nets[n1]:
                    self.nets[n1].append(ref)
            name = n1
        self.invalidate()
        return name

    def disconnect(self, pid, pin):
        ref = f"{pid}.{pin}"
        for name in list(self.nets):
            if ref in self.nets[name]:
                self.nets[name].remove(ref)
                if not self.nets[name]:
                    del self.nets[name]
                self.invalidate()
                return name
        return None

    def set_param(self, pid, key, value):
        if pid not in self.parts:
            return
        self.parts[pid][key] = value
        self.invalidate()

    def set_param_default(self, pid, key):
        if pid in self.parts:
            self.parts[pid].pop(key, None)
            self.invalidate()

    def rename_net(self, old, new):
        new = new.strip()
        if not new or new == old or new in self.nets:
            return False
        if old not in self.nets:
            return False
        self.nets = {(new if k == old else k): v for k, v in self.nets.items()}
        return True

    def problems(self):
        out = []
        seen = {}
        for name, refs in self.nets.items():
            for ref in refs:
                if ref in seen and seen[ref] != name:
                    out.append({"severity": "error", "code": "multi_net",
                                "message": f"{ref} compare in due reti ({seen[ref]}, {name})"})
                seen[ref] = name
        for pid, data in self.parts.items():
            p = self.part(pid)
            if p is None:
                out.append({"severity": "error", "code": "unknown_type",
                            "message": f"{pid}: tipo sconosciuto {data.get('type')!r}",
                            "part": pid})
                continue
            if pid not in self.layout["parts"]:
                out.append({"severity": "warning", "code": "no_layout",
                            "message": f"{pid}: posizione mancante", "part": pid})
            optional = set(p.spec.optional)
            for pin in p.spec.pins:
                if self.net_of(pid, pin) is None and pin not in optional:
                    out.append({"severity": "error", "code": "floating_pin",
                                "message": f"{pid} ({p.type}): pin {pin} scollegato",
                                "part": pid, "pin": pin})
            for key in p.spec.numeric_keys():
                if key in self.parts[pid]:
                    try:
                        to_float(self.parts[pid][key])
                    except Exception:
                        out.append({"severity": "error", "code": "bad_value",
                                    "message": f"{pid}.{key}: valore non numerico",
                                    "part": pid})
        if self.ground is None:
            out.append({"severity": "error", "code": "no_ground",
                        "message": "manca la massa: aggiungi un simbolo Massa"})
        for name, refs in self.nets.items():
            if len(refs) < 2:
                out.append({"severity": "warning", "code": "single_pin_net",
                            "message": f"rete {name}: un solo pin"})
        return out

    def errors(self):
        return [p for p in self.problems() if p["severity"] == "error"]

    def can_simulate(self):
        return not self.errors()

    def save(self, circuit_path, layout_path=None):
        circuit_path.parent.mkdir(parents=True, exist_ok=True)
        circuit_path.write_text(self.to_json(False) + "\n", encoding="utf-8")
        if layout_path is not None:
            layout_path.write_text(self.to_json(True) + "\n", encoding="utf-8")
        self.source = circuit_path
        self.builtin = False


def slugify(name):
    s = re.sub(r"[^a-zA-Z0-9_\- ]", "", name).strip().lower()
    s = re.sub(r"\s+", "_", s)
    return s or "circuito"
