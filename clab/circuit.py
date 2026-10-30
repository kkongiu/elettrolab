import json
import math
from pathlib import Path

from .db import DB
from .units import to_float


class CircuitError(Exception):
    def __init__(self, code, message, **ctx):
        super().__init__(message)
        self.code = code
        self.message = message
        self.ctx = ctx

    def as_dict(self):
        return {"code": self.code, "message": self.message, **self.ctx}


GROUND = {"gnd", "0", "GND", "ground", "GROUND"}


class Circuit:
    def __init__(self, data, db):
        self.raw = data
        self.db = db
        self.id = data.get("id", "circuito")
        self.title = data.get("title", self.id)
        self.ref = data.get("ref", "")
        self.notes = data.get("notes", "")
        self.analysis = data.get("analysis", "dc")
        self.expect = dict(data.get("expect", {}))
        self.tstop = data.get("tstop")
        self.dt = data.get("dt")
        self.nets = {k: list(v) for k, v in data.get("nets", {}).items()}
        self.parts = {}
        for pid, pdata in data.get("parts", {}).items():
            self.parts[pid] = db.part(pid, pdata)
        self.pin_node = {}
        self.pin_net = {}
        self.node_names = []
        self.ground = None
        self.warnings = []
        self._index_nodes()
        self._validate()
        self.n_branches = sum(1 for p in self.parts.values() if p.kind in ("V", "L", "XFMR"))

    def _index_nodes(self):
        for net, pins in self.nets.items():
            if net in GROUND:
                if self.ground is not None:
                    raise CircuitError("multiple_ground", "piu' di una rete di massa", nets=[self.ground, net])
                self.ground = net
        if self.ground is None:
            raise CircuitError("no_ground", "nessuna massa: aggiungi una rete chiamata 'gnd'")
        idx = {}
        n = 0
        for net in self.nets:
            if net in GROUND:
                idx[net] = -1
            else:
                idx[net] = n
                n += 1
        self.node_index = idx
        self.n = n
        self.node_names = [None] * n
        for net, i in idx.items():
            if i >= 0:
                self.node_names[i] = net
        for net, pins in self.nets.items():
            for ref in pins:
                if "." not in ref:
                    raise CircuitError("bad_pin_ref", f"riferimento pin non valido: {ref!r} (usa 'R1.1')", ref=ref)
                pid, pin = ref.rsplit(".", 1)
                if pid not in self.parts:
                    raise CircuitError("unknown_part", f"componente non dichiarato: {pid!r}", part=pid)
                if (pid, pin) in self.pin_net:
                    raise CircuitError(
                        "multi_net",
                        f"il pin {pid}.{pin} compare in due reti ({self.pin_net[(pid, pin)]!r} e {net!r})",
                        part=pid, pin=pin)
                self.pin_node[(pid, pin)] = idx[net]
                self.pin_net[(pid, pin)] = net

    def _validate(self):
        if self.analysis not in ("dc", "transient"):
            raise CircuitError("bad_analysis", f"analisi non supportata: {self.analysis!r}")
        for key in ("dt", "tstop"):
            value = getattr(self, key)
            if value is None:
                continue
            try:
                number = to_float(value)
            except (ValueError, TypeError) as e:
                raise CircuitError("bad_value", f"{key}: valore numerico non valido ({e})",
                                   parameter=key)
            if not math.isfinite(number) or number <= 0:
                raise CircuitError("out_of_range", f"{key}: deve essere un numero finito > 0",
                                   parameter=key)
        if self.analysis == "transient" and self.dt is not None and self.tstop is not None:
            ratio = to_float(self.tstop) / to_float(self.dt)
            if not math.isfinite(ratio) or ratio > 300000:
                raise CircuitError("too_long", "tstop/dt supera il limite di 300000 passi")
            if round(ratio) < 2:
                raise CircuitError("bad_value", "tstop troppo breve rispetto a dt")
        for pid, p in self.parts.items():
            if p.validation_errors:
                issue = p.validation_errors[0]
                raise CircuitError(issue["code"], f"{pid}.{issue['parameter']}: {issue['message']}",
                                   part=pid, parameter=issue["parameter"])
            missing = [pin for pin in p.spec.pins if (pid, pin) not in self.pin_net]
            missing = [m for m in missing if m not in p.spec.optional]
            if missing:
                if p.kind == "POT" and p.get("mode", "divider") == "rheostat":
                    missing = [m for m in missing if m != "2"]
                if missing:
                    raise CircuitError(
                        "floating_pin",
                        f"{pid} ({p.type}): pin non collegati: {', '.join(missing)}",
                        part=pid, pins=missing)
        for net, pins in self.nets.items():
            if len(pins) < 2:
                self.warnings.append(f"la rete {net!r} ha un solo pin: nodo flottante")

    def node(self, pid, pin):
        return self.pin_node.get((pid, pin), -1)

    def connected(self, pid, pin):
        return (pid, pin) in self.pin_node

    def net_of(self, pid, pin):
        return self.pin_net.get((pid, pin))

    def part(self, pid):
        return self.parts[pid]

    def by_kind(self, kind):
        return [(pid, p) for pid, p in self.parts.items() if p.kind == kind]


def load(path, db):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Circuit(data, db)


def from_dict(data, db):
    return Circuit(data, db)
