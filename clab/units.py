import re

_MULT = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "\u00b5": 1e-6, "m": 1e-3,
    "k": 1e3, "K": 1e3, "M": 1e6, "meg": 1e6, "G": 1e9, "": 1.0,
}

_NUM = re.compile(r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([a-zA-Z\u00b5]*)")


def to_float(v):
    if isinstance(v, bool):
        raise ValueError("valore booleano non numerico")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    s = s.replace("\u03a9", "").replace("ohm", "").replace("Ohm", "")
    s = s.replace("F", "").replace("H", "").replace("A", "").replace("V", "").strip()
    s = s.replace(",", ".")
    m = _NUM.fullmatch(s)
    if not m:
        raise ValueError(f"valore non riconosciuto: {v!r}")
    num = float(m.group(1))
    suf = m.group(2)
    if suf.lower() == "meg":
        return num * 1e6
    if suf not in _MULT:
        raise ValueError(f"suffisso sconosciuto: {suf!r} in {v!r}")
    return num * _MULT[suf]


def fmt(v, unit="", digits=3):
    if v is None:
        return "-"
    a = abs(v)
    if a == 0:
        return f"0 {unit}".strip()
    for scale, pre in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""),
                       (1e-3, "m"), (1e-6, "\u00b5"), (1e-9, "n"), (1e-12, "p")):
        if a >= scale * 0.999:
            return f"{v / scale:.{digits}g} {pre}{unit}".strip()
    return f"{v:.{digits}g} {unit}".strip()
