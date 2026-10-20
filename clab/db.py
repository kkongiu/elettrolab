import json
from pathlib import Path

from .units import to_float


class DBError(Exception):
    pass


class PartType:
    def __init__(self, data):
        self.id = data["id"]
        self.kind = data.get("kind", self.id)
        self.name = data.get("name", self.id)
        self.pins = list(data["pins"])
        self.params = dict(data.get("params", {}))
        self.limits = dict(data.get("limits", {}))
        self.learn = data.get("learn", "")
        self.numeric = set(data.get("numeric", []))

    def numeric_keys(self):
        if self.numeric:
            return self.numeric
        out = set()
        for k, v in self.params.items():
            try:
                to_float(v)
            except (ValueError, TypeError):
                continue
            out.add(k)
        return out


class Part:
    def __init__(self, pid, spec, overrides):
        self.id = pid
        self.spec = spec
        self.params = dict(spec.params)
        for k, v in (overrides or {}).items():
            if k in ("type", "id"):
                continue
            self.params[k] = v
        self._numeric = spec.numeric_keys()

    @property
    def type(self):
        return self.spec.id

    @property
    def kind(self):
        return self.spec.kind

    @property
    def name(self):
        return self.spec.name

    def num(self, key):
        return to_float(self.params[key])

    def get(self, key, default=None):
        return self.params.get(key, default)

    def as_dict(self):
        return {"type": self.type, **self.params}


class DB:
    def __init__(self, path):
        self.path = Path(path)
        self.types = {}
        if not self.path.is_dir():
            raise DBError(f"cartella componenti non trovata: {self.path}")
        for f in sorted(self.path.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            spec = PartType(data)
            self.types[spec.id] = spec

    def part(self, pid, data):
        typ = data.get("type")
        if typ not in self.types:
            raise DBError(f"componente sconosciuto: {typ!r} (disponibili: {', '.join(sorted(self.types))})")
        return Part(pid, self.types[typ], data)
