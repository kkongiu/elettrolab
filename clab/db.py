import json
import math
from pathlib import Path

from .units import to_float


PARAMETER_BOUNDS = {
    **{key: {"min": 0.0, "exclusive_min": True} for key in (
        "r", "rtotal", "rcoil", "c", "l", "n", "beta", "ron", "roff",
        "pmax", "imax", "imax2", "vmax", "vn", "freq", "period",
    )},
    **{key: {"min": 0.0} for key in (
        "rd", "vf", "amp", "p", "vbe", "vcesat", "von", "ihold", "rb",
        "vpull", "vdrop", "ki", "t_close", "t_open", "t_soft", "td",
        "dt", "tstop", "vref",
    )},
    "pos": {"min": 0.0, "max": 1.0},
    "duty": {"min": 0.0, "max": 1.0},
}


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
        self.instance_params = set(data.get("instance_params", []))
        self.allowed_params = set(self.params) | set(self.limits) | self.instance_params
        self.learn = data.get("learn", "")
        self.numeric = set(data.get("numeric", []))
        self.optional = list(data.get("optional", []))

    def numeric_keys(self):
        out = set(self.numeric)
        for values in (self.params, self.limits):
            for k, v in values.items():
                try:
                    to_float(v)
                except (ValueError, TypeError):
                    continue
                out.add(k)
        return out

    def validate_instance(self, values):
        errors = []
        for key in values:
            if key in ("type", "id") or key in self.allowed_params:
                continue
            errors.append({"code": "unknown_parameter", "parameter": key,
                           "message": f"parametro non dichiarato per {self.id}: {key}"})

        for key in self.numeric_keys():
            if key not in values:
                continue
            try:
                number = to_float(values[key])
            except (ValueError, TypeError) as e:
                errors.append({"code": "bad_value", "parameter": key,
                               "message": f"{key}: valore numerico non valido ({e})"})
                continue
            if not math.isfinite(number):
                errors.append({"code": "bad_value", "parameter": key,
                               "message": f"{key}: il valore deve essere finito"})
                continue
            bounds = PARAMETER_BOUNDS.get(key, {})
            if "min" in bounds and (number < bounds["min"] or
                                     (bounds.get("exclusive_min") and number == bounds["min"])):
                op = ">" if bounds.get("exclusive_min") else ">="
                errors.append({"code": "out_of_range", "parameter": key,
                               "message": f"{key}: deve essere {op} {bounds['min']}"})
            if "max" in bounds and number > bounds["max"]:
                errors.append({"code": "out_of_range", "parameter": key,
                               "message": f"{key}: deve essere <= {bounds['max']}"})

        for key, default in self.params.items():
            if key not in values:
                continue
            value = values[key]
            if isinstance(default, bool) and not isinstance(value, bool):
                errors.append({"code": "bad_value", "parameter": key,
                               "message": f"{key}: deve essere booleano"})
            elif key == "mode" and value not in ("divider", "rheostat"):
                errors.append({"code": "bad_value", "parameter": key,
                               "message": f"{key}: scegli divider o rheostat"})
            elif key == "wave" and value not in ("sin", "dc"):
                errors.append({"code": "bad_value", "parameter": key,
                               "message": f"{key}: forma d'onda non supportata"})
        return errors


class Part:
    def __init__(self, pid, spec, overrides):
        self.id = pid
        self.spec = spec
        values = {**spec.params, **spec.limits, **(overrides or {})}
        self.validation_errors = spec.validate_instance(values)
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
