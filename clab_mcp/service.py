import copy
import html
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Optional

from clab.circuit import CircuitError
from clab.db import DB, PartType
from clab.document import Document, slugify
from clab.layouts import LAYOUTS
from clab.solver import (SolveError, ac_sweep as solve_ac_sweep,
                         check as check_result, simulate as simulate_circuit)
from clab.schematic import Schematic

ROOT = Path(__file__).resolve().parent.parent
MAX_NODES = 200
MAX_POINTS = 2000
MAX_SWEEP = 50


def data_root() -> Path:
    return Path(os.environ.get("CLAB_DATA_DIR", ROOT / "data")).resolve()


def db() -> DB:
    return DB(data_root() / "components")


def _safe_id(value: str) -> str:
    value = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", value):
        raise ValueError("id non valido: usa lettere, numeri, _ e -")
    return value


def _write_allowed() -> bool:
    return str(os.environ.get("CLAB_MCP_ALLOW_WRITE", "0")).lower() in ("1", "true", "yes")


def _error(code: str, message: str, **ctx) -> dict:
    return {"code": code, "message": message, **ctx}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def catalog() -> dict:
    items = []
    for spec in sorted(db().types.values(), key=lambda s: (s.kind, s.name)):
        items.append({
            "id": spec.id,
            "name": spec.name,
            "kind": spec.kind,
            "pins": list(spec.pins),
            "params": copy.deepcopy(spec.params),
            "limits": copy.deepcopy(spec.limits),
            "instance_params": sorted(spec.instance_params),
            "optional": list(spec.optional),
            "learn": spec.learn,
        })
    return {"count": len(items), "components": items}


def component(cid: str) -> dict:
    spec = db().types.get(cid)
    if spec is None:
        return {"ok": False, "errors": [_error("not_found", f"componente sconosciuto: {cid!r}")]}
    return {
        "ok": True,
        "component": {
            "id": spec.id,
            "name": spec.name,
            "kind": spec.kind,
            "pins": list(spec.pins),
            "params": copy.deepcopy(spec.params),
            "limits": copy.deepcopy(spec.limits),
            "instance_params": sorted(spec.instance_params),
            "optional": list(spec.optional),
            "learn": spec.learn,
        },
        "example": {"parts": {"X1": {"type": spec.id}}},
    }


def _circuit_paths(cid: str):
    cid = _safe_id(cid)
    for folder, source in ((data_root() / "exercises", "builtin"),
                           (data_root() / "projects", "project")):
        path = folder / f"{cid}.json"
        if path.exists():
            return path, source
    return None, None


def _layout_for(cid: str, source: str) -> Optional[dict]:
    if source == "builtin":
        return copy.deepcopy(LAYOUTS.get(cid))
    path = data_root() / "projects" / f"{cid}.layout.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def list_exercises() -> dict:
    items = []
    for folder, source in ((data_root() / "exercises", "builtin"),
                           (data_root() / "projects", "project")):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            if path.name.endswith(".layout.json"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append({
                "id": data.get("id", path.stem),
                "title": data.get("title", path.stem),
                "analysis": data.get("analysis", "dc"),
                "source": source,
            })
    items.sort(key=lambda x: (x["source"] != "builtin", x["id"]))
    return {"count": len(items), "exercises": items}


def get_circuit(cid: str) -> dict:
    path, source = _circuit_paths(cid)
    if path is None:
        return {"ok": False, "errors": [_error("not_found", f"circuito non trovato: {cid!r}")]}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "ok": True,
        "id": data.get("id", cid),
        "circuit": data,
        "layout": _layout_for(data.get("id", cid), source),
        "source": source,
        "path": str(path),
    }


def _document(circuit: dict) -> Document:
    return Document(circuit, db())


def _problems(doc: Document) -> tuple[list, list]:
    problems = doc.problems()
    return ([p for p in problems if p["severity"] == "error"],
            [p for p in problems if p["severity"] == "warning"])


def validate(circuit: dict) -> dict:
    if not isinstance(circuit, dict):
        return {"ok": False, "errors": [_error("invalid", "circuit deve essere un oggetto JSON")]}
    try:
        doc = _document(circuit)
    except Exception as e:
        return {"ok": False, "errors": [_error("invalid", str(e))]}
    errors, warnings = _problems(doc)
    if len(doc.nets) > MAX_NODES:
        errors.append(_error("too_large", f"troppe reti: {len(doc.nets)} > {MAX_NODES}"))
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def render_schematic(circuit: Optional[dict] = None, cid: Optional[str] = None,
                     layout: Optional[dict] = None) -> dict:
    if circuit is None:
        if not cid:
            return {"ok": False, "errors": [_error("invalid", "serve circuit oppure id")]}
        loaded = get_circuit(cid)
        if not loaded.get("ok"):
            return loaded
        circuit = loaded["circuit"]
        layout = layout if layout is not None else loaded.get("layout")
    try:
        doc = Document(circuit, db(), layout=layout)
    except Exception as e:
        return {"ok": False, "errors": [_error("invalid", str(e))]}
    errors, warnings = _problems(doc)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    if len(doc.parts) > MAX_NODES:
        return {"ok": False, "errors": [_error("too_large", "troppi componenti per lo schema SVG")],
                "warnings": warnings}
    schematic = Schematic(None, doc)
    extents = [schematic.part_bbox(pid) for pid in doc.parts]
    extents.extend((x, y, x, y) for path in schematic.paths for x, y in path.poly)
    min_x = min([0.0] + [box[0] for box in extents]) - 24
    min_y = min([0.0] + [box[1] for box in extents]) - 24
    max_x = max([1100.0] + [box[2] for box in extents]) + 24
    max_y = max([420.0] + [box[3] for box in extents]) + 24
    width, height = max_x - min_x, max_y - min_y
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Schema {html.escape(str(doc.meta.get("title", doc.meta.get("id", "circuito"))))}" '
        f'viewBox="{min_x:g} {min_y:g} {width:g} {height:g}" '
        f'width="{width:g}" height="{height:g}">',
        f'<rect x="{min_x:g}" y="{min_y:g}" width="{width:g}" '
        f'height="{height:g}" fill="#ffffff"/>',
        '<g fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">',
    ]
    if schematic.rail:
        x0, x1, y = schematic.rail
        lines.append(f'<path d="M{x0:g} {y:g} H{x1:g}" stroke="#2563eb" stroke-width="3"/>')
    for _name, x0, x1, y in schematic.buses:
        lines.append(f'<path d="M{x0:g} {y:g} H{x1:g}"/>')
    for path in schematic.paths:
        for i, (a, b) in enumerate(zip(path.poly, path.poly[1:])):
            splits = schematic.cross.get((path.key, i), [])
            if splits and abs(a[0] - b[0]) < 1e-9:
                x = a[0]
                y0, y1 = sorted((a[1], b[1]))
                cur = y0
                for _sx, cy in sorted(splits, key=lambda point: point[1]):
                    top = max(y0, cy - 6)
                    bot = min(y1, cy + 6)
                    if top > cur:
                        lines.append(f'<path d="M{x:g} {cur:g} V{top:g}"/>')
                    cur = max(cur, bot)
                if cur < y1:
                    lines.append(f'<path d="M{x:g} {cur:g} V{y1:g}"/>')
            else:
                lines.append(f'<path d="M{a[0]:g} {a[1]:g} L{b[0]:g} {b[1]:g}"/>')
    lines.append("</g>")
    lines.append('<g fill="#1f2937" stroke="none">')
    for x, y in schematic.junctions:
        lines.append(f'<circle cx="{x:g}" cy="{y:g}" r="3"/>')
    lines.append("</g>")
    lines.append('<g font-family="sans-serif" text-anchor="middle">')
    for net in doc.nets:
        if net == doc.ground:
            continue
        path = next((item for item in schematic.paths if item.net == net), None)
        if path and len(path.poly) > 1:
            x, y = path.at(path.total / 2)
            lines.append(f'<text x="{x:g}" y="{y-7:g}" font-size="9" '
                         f'fill="#0a5bd3">{html.escape(net)}</text>')
    for pid in doc.parts:
        part = doc.part(pid)
        x, y, _rot = doc.position(pid)
        x0, y0, x1, y1 = schematic.part_bbox(pid)
        lines.append(f'<rect x="{x0:g}" y="{y0:g}" width="{x1-x0:g}" '
                     f'height="{y1-y0:g}" rx="6" fill="#f8fafc" '
                     'stroke="#1f2937" stroke-width="2"/>')
        lines.append(f'<text x="{x:g}" y="{y-3:g}" font-size="14" '
                     f'font-weight="bold" fill="#1f2937">{html.escape(pid)}</text>')
        lines.append(f'<text x="{x:g}" y="{y+15:g}" font-size="10" '
                     f'fill="#64748b">{html.escape(part.name)}</text>')
        for pin in part.spec.pins:
            px, py = schematic.pin_position(pid, pin)
            lines.append(f'<circle cx="{px:g}" cy="{py:g}" r="3.5" '
                         'fill="#ffffff" stroke="#1f2937" stroke-width="1.5"/>')
            dx = -6 if px < x else 6
            anchor = "end" if px < x else "start"
            lines.append(f'<text x="{px+dx:g}" y="{py-5:g}" text-anchor="{anchor}" '
                         f'font-size="9" fill="#475569">{html.escape(pin)}</text>')
    lines.append("</g></svg>")
    return {"ok": True, "format": "image/svg+xml", "svg": "".join(lines),
            "parts": len(doc.parts), "nets": len(doc.nets), "warnings": warnings}


def _compile(circuit: dict):
    try:
        doc = _document(circuit)
    except Exception as e:
        return None, [_error("invalid", str(e))]
    errors, _ = _problems(doc)
    if len(doc.nets) > MAX_NODES:
        errors.append(_error("too_large", f"troppe reti: {len(doc.nets)} > {MAX_NODES}"))
    if errors:
        return None, errors
    try:
        return doc.to_circuit(), []
    except CircuitError as e:
        return None, [e.as_dict()]


def _summary(values) -> dict:
    return {"min": float(min(values)), "max": float(max(values)), "final": float(values[-1])}


def _result(circ, res, include_waveforms: bool, max_points: int) -> dict:
    max_points = max(1, min(int(max_points), MAX_POINTS))
    out = {
        "ok": bool(res.ok),
        "analysis": res.analysis,
        "nodes": {k: float(v) for k, v in res.nodes.items()},
        "currents": {k: float(v) for k, v in res.currents.items()},
        "power": {k: float(v) for k, v in res.power.items()},
        "violations": _json_safe(res.violations),
        "checks": _json_safe(res.checks),
        "notes": list(res.notes),
        "residual": float(res.residual),
        "n_nodes": int(circ.n),
        "n_parts": len(circ.parts),
    }
    if res.time is not None:
        n = len(res.time)
        if n <= max_points:
            idx = list(range(n))
        else:
            step = (n - 1) / (max_points - 1)
            idx = sorted({int(round(i * step)) for i in range(max_points)})
        out["n_points"] = n
        out["dt"] = float(res.time[1] - res.time[0]) if n > 1 else 0.0
        out["duration"] = float(res.time[-1])
        out["summary"] = {sig: _summary(vals) for sig, vals in res.waves.items()}
        if include_waveforms:
            out["time"] = [float(res.time[i]) for i in idx]
            out["waves"] = {sig: [float(vals[i]) for i in idx]
                            for sig, vals in res.waves.items()}
    return out


def simulate(circuit: dict, include_waveforms: bool = False, max_points: int = 200) -> dict:
    circ, errors = _compile(circuit)
    if circ is None:
        return {"ok": False, "errors": errors}
    try:
        res = simulate_circuit(circ)
        check_result(circ, res)
    except (CircuitError, SolveError) as e:
        payload = e.as_dict() if hasattr(e, "as_dict") else _error("solve", str(e))
        return {"ok": False, "errors": [payload]}
    return _result(circ, res, include_waveforms, max_points)


def ac_sweep(circuit: dict, source: str, probe: str, fstart: float = 1.0,
             fstop: float = 1e6, points: int = 101) -> dict:
    circ, errors = _compile(circuit)
    if circ is None:
        return {"ok": False, "errors": errors}
    try:
        result = solve_ac_sweep(circ, source, probe, fstart, fstop, points)
    except SolveError as e:
        return {"ok": False, "errors": [e.as_dict()]}
    return {
        "ok": True,
        "source": source,
        "probe": probe,
        "frequency": [float(v) for v in result["frequency"]],
        "magnitude_db": [float(v) for v in result["magnitude_db"]],
        "phase_deg": [float(v) for v in result["phase_deg"]],
    }


def check(circuit: Optional[dict] = None, cid: Optional[str] = None) -> dict:
    if circuit is None:
        if not cid:
            return {"ok": False, "errors": [_error("invalid", "serve circuit oppure id")]}
        loaded = get_circuit(cid)
        if not loaded.get("ok"):
            return loaded
        circuit = loaded["circuit"]
    circ, errors = _compile(circuit)
    if circ is None:
        return {"ok": False, "errors": errors}
    try:
        res = simulate_circuit(circ)
        check_result(circ, res)
    except (CircuitError, SolveError) as e:
        return {"ok": False, "errors": [e.as_dict() if hasattr(e, "as_dict") else _error("solve", str(e))]}
    return {
        "ok": bool(res.ok),
        "checks": _json_safe(res.checks),
        "violations": _json_safe(res.violations),
    }


def sweep(circuit: dict, part: str, param: str, values: list, signal: str) -> dict:
    if part not in circuit.get("parts", {}):
        return {"ok": False, "errors": [_error("not_found", f"componente non presente: {part}")]}
    if not isinstance(values, list) or not values or len(values) > MAX_SWEEP:
        return {"ok": False, "errors": [_error("invalid", f"values deve avere 1..{MAX_SWEEP} elementi")]}
    rows = []
    for value in values:
        data = copy.deepcopy(circuit)
        data["parts"][part][param] = value
        result = simulate(data, include_waveforms=False)
        if not result.get("ok") and result.get("errors"):
            rows.append({"value": value, "ok": False, "errors": result["errors"]})
            continue
        vals = result.get("summary", {}).get(signal)
        if vals is None and result.get("analysis") == "dc":
            if signal.startswith("V(") and signal.endswith(")"):
                v = result["nodes"].get(signal[2:-1])
            elif signal.startswith("I(") and signal.endswith(")"):
                v = result["currents"].get(signal[2:-1])
            else:
                v = None
            if v is not None:
                vals = {"min": float(v), "max": float(v), "final": float(v)}
        if vals is None:
            rows.append({"value": value, "ok": False,
                         "errors": [_error("signal", f"segnale non trovato: {signal}")]})
            continue
        rows.append({"value": value, "ok": True, "signal": signal,
                     "min": vals.get("min"), "max": vals.get("max"),
                     "final": vals.get("final"),
                     "violations": result.get("violations", [])})
    return {"ok": all(r.get("ok") for r in rows), "rows": rows}


def add_component(definition: dict, overwrite: bool = False) -> dict:
    if not _write_allowed():
        return {"ok": False, "errors": [_error("write_disabled",
                                               "imposta CLAB_MCP_ALLOW_WRITE=1 per scrivere")]}
    try:
        cid = _safe_id(definition.get("id", ""))
        PartType(definition)
    except Exception as e:
        return {"ok": False, "errors": [_error("schema_error", str(e))]}
    folder = data_root() / "components"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{cid}.json"
    if path.exists() and not overwrite:
        return {"ok": False, "errors": [_error("exists", f"{path.name} esiste gia'", path=str(path))]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(definition, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "id": cid, "path": str(path)}


def add_exercise(circuit: dict, layout: Optional[dict] = None, overwrite: bool = False) -> dict:
    if not _write_allowed():
        return {"ok": False, "errors": [_error("write_disabled",
                                               "imposta CLAB_MCP_ALLOW_WRITE=1 per scrivere")]}
    if not isinstance(circuit, dict):
        return {"ok": False, "errors": [_error("invalid", "circuit deve essere un oggetto JSON")]}
    cid = circuit.get("id") or slugify(circuit.get("title", "circuito"))
    try:
        cid = _safe_id(cid)
    except ValueError as e:
        return {"ok": False, "errors": [_error("invalid", str(e))]}
    result = validate(circuit)
    if not result["ok"]:
        return result
    folder = data_root() / "projects"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{cid}.json"
    layout_path = folder / f"{cid}.layout.json"
    if (path.exists() or layout_path.exists()) and not overwrite:
        return {"ok": False, "errors": [_error("exists", f"{cid} esiste gia'", path=str(path))]}
    path.write_text(json.dumps(circuit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if layout is not None:
        layout_path.write_text(json.dumps(layout, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    return {"ok": True, "id": cid, "path": str(path),
            "layout_path": str(layout_path) if layout is not None else None}


def read_doc(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name or ""):
        raise ValueError("nome documento non valido")
    docs = (ROOT / "docs").resolve()
    path = (docs / name).resolve()
    if not path.is_relative_to(docs) or not path.is_file():
        raise FileNotFoundError(name)
    return path.read_text(encoding="utf-8")


def schema() -> dict:
    return {
        "type": "object",
        "required": ["parts", "nets"],
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "notes": {"type": "string"},
            "analysis": {"enum": ["dc", "transient"]},
            "tstop": {"type": "number"},
            "dt": {"type": "number"},
            "parts": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "required": ["type"],
                    "properties": {"type": {"type": "string"}},
                },
            },
            "nets": {
                "type": "object",
                "additionalProperties": {
                    "type": "array", "items": {"type": "string"},
                },
            },
            "expect": {"type": "object"},
        },
    }
