import math

import numpy as np

from .units import to_float


class SolveError(Exception):
    def __init__(self, code, message, **ctx):
        super().__init__(message)
        self.code = code
        self.message = message
        self.ctx = ctx

    def as_dict(self):
        return {"code": self.code, "message": self.message, **self.ctx}


class Result:
    def __init__(self, circ, analysis):
        self.circ = circ
        self.analysis = analysis
        self.nodes = {}
        self.currents = {}
        self.power = {}
        self.violations = []
        self.time = None
        self.waves = {}
        self.checks = []
        self.ok = True
        self.notes = []
        self.relay_states = {}
        self.residual = 0.0

    def value(self, sig):
        if self.waves and sig in self.waves:
            return self.waves[sig]
        if sig.startswith("V("):
            net = sig[2:-1]
            if net in self.nodes:
                return np.array([self.nodes[net]])
        if sig.startswith("I("):
            pid = sig[2:-1]
            if pid in self.currents:
                return np.array([self.currents[pid]])
        return None

    def violations_of(self, pid):
        return [v for v in self.violations if v.get("part") == pid]


def simulate(circ):
    if circ.analysis == "dc":
        return _dc(circ)
    if circ.analysis == "transient":
        return _tran(circ)
    if circ.analysis == "schematic":
        raise SolveError("schematic_only", "questo progetto contiene modelli schematici non simulabili")
    raise SolveError("bad_analysis", f"analisi non supportata: {circ.analysis!r}")


def ac_sweep(circ, source, probe, fstart=1.0, fstop=1e6, points=101):
    """Small-signal sweep for supported linear networks, normalized to a 1 V source."""
    if source not in circ.parts or circ.part(source).kind != "V":
        raise SolveError("bad_source", f"sorgente AC non valida: {source!r}")
    if probe not in circ.nets:
        raise SolveError("bad_probe", f"rete di uscita non valida: {probe!r}")
    try:
        fstart, fstop = to_float(fstart), to_float(fstop)
        points = int(points)
    except (TypeError, ValueError):
        raise SolveError("bad_frequency", "intervallo di frequenza o numero di punti non valido")
    if (not math.isfinite(fstart) or not math.isfinite(fstop) or
            fstart <= 0 or fstop <= fstart or not 2 <= points <= 301):
        raise SolveError("bad_frequency", "usa 0 < fstart < fstop e 2..301 punti")

    supported = {"R", "SPK", "LAMP", "V", "C", "L", "POT", "SW", "XFMR", "GND"}
    for pid, part in circ.parts.items():
        if part.kind not in supported:
            raise SolveError("unsupported_ac",
                             f"{pid} ({part.type}) non supportato nell'analisi AC", part=pid)
        if part.kind == "SW" and any(k in part.params for k in (
                "freq", "period", "ki", "t_close", "t_open", "t_soft")):
            raise SolveError("unsupported_ac",
                             f"{pid}: il convertitore switching non ha un modello AC linearizzato",
                             part=pid)

    branch_pids = [pid for pid, p in circ.parts.items() if p.kind in ("V", "XFMR")]
    if circ.n + len(branch_pids) > 80:
        raise SolveError("too_large", "l'analisi AC supporta al massimo 80 incognite")
    branch = {pid: circ.n + i for i, pid in enumerate(branch_pids)}
    frequencies = np.geomspace(fstart, fstop, points)
    gain = np.empty(points, dtype=complex)
    for fi, frequency in enumerate(frequencies):
        size = circ.n + len(branch_pids)
        A = np.zeros((size, size), dtype=complex)
        b = np.zeros(size, dtype=complex)
        omega = 2 * math.pi * frequency
        for pid, part in circ.parts.items():
            kind = part.kind
            if kind in ("R", "SPK", "LAMP"):
                pins = ("+", "-") if kind == "SPK" else ("1", "2")
                a, c = (circ.node(pid, pin) for pin in pins)
                _stamp_g(A, a, c, 1.0 / part.num("r"))
            elif kind == "C":
                _stamp_g(A, circ.node(pid, "+"), circ.node(pid, "-"),
                         1j * omega * part.num("c"))
            elif kind == "L":
                _stamp_g(A, circ.node(pid, "1"), circ.node(pid, "2"),
                         1.0 / (1j * omega * part.num("l")))
            elif kind == "POT":
                r1, r2, w = (circ.node(pid, pin) for pin in ("1", "2", "W"))
                total = part.num("rtotal")
                pos = min(max(part.num("pos"), 0.0), 1.0)
                _stamp_g(A, r1, w, 1.0 / max(total * pos, 1e-6))
                if part.get("mode", "divider") != "rheostat" and circ.connected(pid, "2"):
                    _stamp_g(A, w, r2, 1.0 / max(total * (1 - pos), 1e-6))
            elif kind == "SW":
                a, c = circ.node(pid, "1"), circ.node(pid, "2")
                resistance = part.num("ron") if part.get("closed", True) else part.num("roff")
                _stamp_g(A, a, c, 1.0 / max(resistance, 1e-6))
            elif kind == "V":
                a, c = circ.node(pid, "+"), circ.node(pid, "-")
                k = branch[pid]
                if a >= 0:
                    A[k, a] += 1
                    A[a, k] += 1
                if c >= 0:
                    A[k, c] -= 1
                    A[c, k] -= 1
                b[k] = 1.0 if pid == source else 0.0
            elif kind == "XFMR":
                pp, pm = circ.node(pid, "P+"), circ.node(pid, "P-")
                sp, sm = circ.node(pid, "S+"), circ.node(pid, "S-")
                ratio = part.num("n")
                k = branch[pid]
                if sp >= 0:
                    A[k, sp] += 1
                    A[sp, k] += 1
                if sm >= 0:
                    A[k, sm] -= 1
                    A[sm, k] -= 1
                if pp >= 0:
                    A[k, pp] -= ratio
                    A[pp, k] -= ratio
                if pm >= 0:
                    A[k, pm] += ratio
                    A[pm, k] += ratio
        x = _solve(A, b)
        node = circ.node_index[probe]
        gain[fi] = x[node] if node >= 0 else 0.0
    magnitude_db = 20.0 * np.log10(np.maximum(np.abs(gain), 1e-15))
    phase_deg = np.angle(gain, deg=True)
    return {"frequency": frequencies, "gain": gain,
            "magnitude_db": magnitude_db, "phase_deg": phase_deg,
            "source": source, "probe": probe}


def _stamp_g(A, a, c, g):
    if a >= 0:
        A[a, a] += g
    if c >= 0:
        A[c, c] += g
    if a >= 0 and c >= 0:
        A[a, c] -= g
        A[c, a] -= g


def _stamp_i(b, a, c, i):
    if a >= 0:
        b[a] -= i
    if c >= 0:
        b[c] += i


def _branch(circ, A, b, k, a, c, v, req=0.0, hist=0.0):
    if a >= 0:
        A[k, a] += 1.0
        A[a, k] += 1.0
    if c >= 0:
        A[k, c] -= 1.0
        A[c, k] -= 1.0
    A[k, k] -= req
    b[k] = v - req * hist


def _pin_voltage(circ, x, pid, pin):
    node = circ.node(pid, pin)
    return float(x[node]) if node >= 0 else 0.0


def _bq24074_charge_current(circ, pid):
    iset = circ.node(pid, "ISET")
    for rid, resistor in circ.by_kind("R"):
        r1, r2 = circ.node(rid, "1"), circ.node(rid, "2")
        if iset in (r1, r2) and circ.ground in (
                circ.net_of(rid, "1"), circ.net_of(rid, "2")):
            return min(1.5, 890.0 / resistor.num("r"))
    return 0.0


def _feedback_target(circ, pid, default=5.0):
    fb = circ.node(pid, "FB")
    out = circ.node(pid, "VOUT")
    rtop = rbottom = None
    for rid, resistor in circ.by_kind("R"):
        n1, n2 = circ.node(rid, "1"), circ.node(rid, "2")
        if fb not in (n1, n2):
            continue
        other = n2 if n1 == fb else n1
        if other == out:
            rtop = resistor.num("r")
        elif circ.net_of(rid, "1" if n1 == other else "2") == circ.ground:
            rbottom = resistor.num("r")
    if not rtop or not rbottom:
        return default
    return 0.595 * (1.0 + rtop / rbottom)


def _tps2553_limit(circ, pid):
    ilim = circ.node(pid, "ILIM")
    for rid, resistor in circ.by_kind("R"):
        n1, n2 = circ.node(rid, "1"), circ.node(rid, "2")
        if ilim in (n1, n2) and circ.ground in (
                circ.net_of(rid, "1"), circ.net_of(rid, "2")):
            r_kohm = resistor.num("r") / 1000.0
            if r_kohm > 0:
                return 23.950 / (r_kohm ** 0.977)
    return 1.0


def _resistive_load_current(circ, x, node, excluded):
    current = 0.0
    if node < 0:
        return current
    for pid, part in circ.parts.items():
        if pid == excluded or part.kind not in ("R", "SPK", "LAMP"):
            continue
        if part.kind == "SPK":
            pins = ("+", "-")
        else:
            pins = ("1", "2")
        n1, n2 = (circ.node(pid, pin) for pin in pins)
        resistance = part.num("r")
        if n1 == node and n2 != node:
            current += (_pin_voltage(circ, x, pid, pins[0]) -
                        _pin_voltage(circ, x, pid, pins[1])) / resistance
        elif n2 == node and n1 != node:
            current += (_pin_voltage(circ, x, pid, pins[1]) -
                        _pin_voltage(circ, x, pid, pins[0])) / resistance
    return max(0.0, current)


def _update_power_models(circ, x, old):
    state = dict(old)
    for pid, part in circ.parts.items():
        if part.type == "bq24074":
            input_ok = _pin_voltage(circ, x, pid, "IN") >= 4.35
            ce_enabled = _pin_voltage(circ, x, pid, "CE") < 0.8
            battery_needs_charge = _pin_voltage(circ, x, pid, "BAT") < 4.2
            state[f"{pid}:input"] = input_ok
            state[f"{pid}:charge"] = input_ok and ce_enabled and battery_needs_charge
        elif part.type == "tps61023":
            enabled = (
                _pin_voltage(circ, x, pid, "VIN") >= 1.8 and
                _pin_voltage(circ, x, pid, "EN") >= 1.2)
            state[f"{pid}:enabled"] = enabled
            if enabled:
                nominal = _feedback_target(circ, pid)
                vfb = _pin_voltage(circ, x, pid, "FB")
                ratio = 0.595 / nominal
                target = state.get(f"{pid}:target", nominal)
                target += (0.595 - vfb) / ratio
                state[f"{pid}:target"] = min(5.5, max(2.2, target))
                vout = _pin_voltage(circ, x, pid, "VOUT")
                vin = max(0.1, _pin_voltage(circ, x, pid, "VIN"))
                iout = max(0.0, (state[f"{pid}:target"] - vout) / 0.12)
                state[f"{pid}:iin"] = iout * max(vout, 0.0) / (0.9 * vin)
        elif part.type == "tps2553":
            enabled = (
                _pin_voltage(circ, x, pid, "IN") >= 2.5 and
                _pin_voltage(circ, x, pid, "EN") >= 1.1)
            state[f"{pid}:enabled"] = enabled
            if enabled:
                out = circ.node(pid, "OUT")
                limit = _tps2553_limit(circ, pid)
                load = _resistive_load_current(circ, x, out, pid)
                state[f"{pid}:limited"] = load >= limit * 0.999
            else:
                state[f"{pid}:limited"] = False
        elif part.type == "protection_liion_1s":
            vcell = (_pin_voltage(circ, x, pid, "B+") -
                     _pin_voltage(circ, x, pid, "B-"))
            state[f"{pid}:enabled"] = 2.5 <= vcell <= 4.3
    return state


def _model_states_equal(a, b):
    if a.keys() != b.keys():
        return False
    return all(math.isclose(a[key], b[key], rel_tol=1e-8, abs_tol=1e-9)
               if isinstance(a[key], float) and isinstance(b[key], float)
               else a[key] == b[key] for key in a)


def _stamp_ic(circ, A, b, pid, part, state):
    if part.type == "bq24074":
        if state.get(f"{pid}:input", False):
            _stamp_g(A, circ.node(pid, "IN"), circ.node(pid, "OUT"), 1.0 / 0.08)
        else:
            _stamp_g(A, circ.node(pid, "BAT"), circ.node(pid, "OUT"), 1.0 / 0.12)
        if state.get(f"{pid}:charge", False):
            _stamp_i(b, circ.node(pid, "OUT"), circ.node(pid, "BAT"),
                     _bq24074_charge_current(circ, pid))
    elif part.type == "tps61023":
        if state.get(f"{pid}:enabled", False):
            out = circ.node(pid, "VOUT")
            conductance = 1.0 / 0.12
            _stamp_g(A, out, -1, conductance)
            if out >= 0:
                target = state.get(f"{pid}:target", _feedback_target(circ, pid))
                b[out] += conductance * target
            _stamp_i(b, circ.node(pid, "VIN"), -1, state.get(f"{pid}:iin", 0.0))
    elif part.type == "tps2553":
        input_node, output_node = circ.node(pid, "IN"), circ.node(pid, "OUT")
        if state.get(f"{pid}:enabled", False) and state.get(f"{pid}:limited", False):
            _stamp_g(A, input_node, output_node, 1e-9)
            _stamp_i(b, input_node, output_node, _tps2553_limit(circ, pid))
        else:
            resistance = 0.08 if state.get(f"{pid}:enabled", False) else 1e9
            _stamp_g(A, input_node, output_node, 1.0 / resistance)
    elif part.type == "protection_liion_1s":
        resistance = 0.01 if state.get(f"{pid}:enabled", False) else 1e9
        _stamp_g(A, circ.node(pid, "B+"), circ.node(pid, "P+"), 1.0 / resistance)
        _stamp_g(A, circ.node(pid, "B-"), circ.node(pid, "P-"), 1.0 / resistance)
    elif part.type in ("usb_esd_array", "usb_vbus_tvs"):
        # Nominally open protection devices get tiny leakage paths for DC convergence.
        for pin in part.spec.pins:
            _stamp_g(A, circ.node(pid, pin), -1, 1e-9)
        return
    else:
        raise SolveError("unsupported", f"{pid}: componente non simulabile ({part.type})", part=pid)


DIODES = ("LED", "D")


def _source_v(p, t, mode):
    if p.get("wave") == "sin":
        if mode == "dc":
            return to_float(p.get("offset", 0.0))
        amp = p.get("amp")
        if amp is None and "vrms" in p.params:
            amp = to_float(p.get("vrms")) * math.sqrt(2.0)
        amp = to_float(amp if amp is not None else 0.0)
        off = to_float(p.get("offset", 0.0))
        f = to_float(p.get("freq", 50.0))
        return off + amp * math.sin(2.0 * math.pi * f * t)
    return p.num("v")


def _switch_closed(p, t, mode, duty=None):
    closed = bool(p.get("closed", True))
    if mode == "dc":
        return closed
    period = None
    if "freq" in p.params:
        f = p.num("freq")
        if f > 0:
            period = 1.0 / f
    elif "period" in p.params:
        pv = p.num("period")
        if pv > 0:
            period = pv
    if period is not None:
        if duty is None:
            duty = p.num("duty") if "duty" in p.params else 0.5
        duty = min(max(duty, 0.0), 1.0)
        soft = p.num("t_soft") if "t_soft" in p.params else 0.0
        if soft > 0 and t < soft:
            duty *= t / soft
        return (t % period) / period < duty
    if "t_close" in p.params and t >= p.num("t_close"):
        closed = True
    if "t_open" in p.params and t >= p.num("t_open"):
        closed = False
    return closed


def _build(circ, mode, t, dt, vprev, iprev, led_on, relay_on, q_on, mos_on, ctrl):
    n = circ.n
    N = n + circ.n_branches
    A = np.zeros((N, N))
    b = np.zeros(N)
    br = {}
    for pid, p in circ.parts.items():
        if p.kind in ("V", "L", "XFMR"):
            br[pid] = n + len(br)

    for pid, p in circ.parts.items():
        kind = p.kind
        if kind in ("R", "SPK", "LAMP"):
            if kind == "SPK":
                a, c = circ.node(pid, "+"), circ.node(pid, "-")
            else:
                a, c = circ.node(pid, "1"), circ.node(pid, "2")
            r = p.num("r")
            if r <= 0:
                raise SolveError("bad_value", f"{pid}: resistenza non positiva", part=pid)
            _stamp_g(A, a, c, 1.0 / r)
        elif kind == "V":
            a, c = circ.node(pid, "+"), circ.node(pid, "-")
            _branch(circ, A, b, br[pid], a, c, _source_v(p, t, mode))
        elif kind == "L":
            a, c = circ.node(pid, "1"), circ.node(pid, "2")
            l = p.num("l")
            if mode == "dc" or l <= 0:
                _branch(circ, A, b, br[pid], a, c, 0.0)
            else:
                req = l / dt
                _branch(circ, A, b, br[pid], a, c, 0.0, req=req, hist=iprev.get(pid, 0.0))
        elif kind == "XFMR":
            pp, pm = circ.node(pid, "P+"), circ.node(pid, "P-")
            sp, sm = circ.node(pid, "S+"), circ.node(pid, "S-")
            nn = p.num("n")
            k = br[pid]
            if sp >= 0:
                A[k, sp] += 1.0
                A[sp, k] += 1.0
            if sm >= 0:
                A[k, sm] -= 1.0
                A[sm, k] -= 1.0
            if pp >= 0:
                A[k, pp] -= nn
                A[pp, k] -= nn
            if pm >= 0:
                A[k, pm] += nn
                A[pm, k] += nn
        elif kind == "C":
            if mode == "dc":
                continue
            a, c = circ.node(pid, "+"), circ.node(pid, "-")
            g = p.num("c") / dt
            _stamp_g(A, a, c, g)
            if a >= 0:
                b[a] += g * (vprev[a] if a >= 0 else 0.0)
            if c >= 0:
                b[c] -= g * (vprev[c] if c >= 0 else 0.0)
        elif kind in DIODES:
            a, k = circ.node(pid, "A"), circ.node(pid, "K")
            vf = p.num("vf")
            rd = max(p.num("rd"), 1e-3)
            if led_on.get(pid):
                g = 1.0 / rd
                _stamp_g(A, a, k, g)
                if a >= 0:
                    b[a] += g * vf
                if k >= 0:
                    b[k] -= g * vf
            else:
                _stamp_g(A, a, k, 1e-9)
        elif kind == "SW":
            a, c = circ.node(pid, "1"), circ.node(pid, "2")
            duty = ctrl.get(pid) if ctrl else None
            r = p.num("ron") if _switch_closed(p, t, mode, duty) else p.num("roff")
            _stamp_g(A, a, c, 1.0 / max(r, 1e-6))
        elif kind == "POT":
            r1, r2, w = circ.node(pid, "1"), circ.node(pid, "2"), circ.node(pid, "W")
            rt = p.num("rtotal")
            pos = min(max(p.num("pos"), 0.0), 1.0)
            _stamp_g(A, r1, w, 1.0 / max(rt * pos, 1e-6))
            if p.get("mode", "divider") != "rheostat" and circ.connected(pid, "2"):
                _stamp_g(A, w, r2, 1.0 / max(rt * (1.0 - pos), 1e-6))
        elif kind in ("RELAY", "RELAY2"):
            cp, cm = circ.node(pid, "COIL+"), circ.node(pid, "COIL-")
            _stamp_g(A, cp, cm, 1.0 / max(p.num("rcoil"), 1e-6))
            ron, roff = p.num("ron"), p.num("roff")
            on = bool(relay_on.get(pid))
            if kind == "RELAY":
                poles = [("COM", "NC", "NO")]
            else:
                poles = [("COM1", "NC1", "NO1"), ("COM2", "NC2", "NO2")]
            for com, nc, no in poles:
                if not circ.connected(pid, com):
                    continue
                a = circ.node(pid, com)
                for pin, closed in ((nc, not on), (no, on)):
                    if circ.connected(pid, pin):
                        _stamp_g(A, a, circ.node(pid, pin),
                                 1.0 / max(ron if closed else roff, 1e-6))
        elif kind == "NPN":
            c, b_, e = circ.node(pid, "C"), circ.node(pid, "B"), circ.node(pid, "E")
            vbe = p.num("vbe")
            rb = max(p.num("rb"), 1e-3)
            st = q_on.get(pid, 0)
            if st == 0:
                _stamp_g(A, b_, e, 1e-9)
                _stamp_g(A, c, e, 1e-9)
            else:
                gb = 1.0 / rb
                _stamp_g(A, b_, e, gb)
                if b_ >= 0:
                    b[b_] += gb * vbe
                if e >= 0:
                    b[e] -= gb * vbe
                if st == 1:
                    gm = p.num("beta") / rb
                    if c >= 0 and b_ >= 0:
                        A[c, b_] += gm
                    if c >= 0 and e >= 0:
                        A[c, e] -= gm
                    if e >= 0 and b_ >= 0:
                        A[e, b_] -= gm
                    if e >= 0:
                        A[e, e] += gm
                    if c >= 0:
                        b[c] += gm * vbe
                    if e >= 0:
                        b[e] -= gm * vbe
                else:
                    gs = 1.0 / max(p.num("ron"), 1e-6)
                    _stamp_g(A, c, e, gs)
                    if c >= 0:
                        b[c] += gs * p.num("vcesat")
                    if e >= 0:
                        b[e] -= gs * p.num("vcesat")
        elif kind == "PUT":
            a, k = circ.node(pid, "A"), circ.node(pid, "K")
            st = q_on.get(pid, 0)
            if st == 0:
                _stamp_g(A, a, k, 1e-9)
            else:
                g = 1.0 / max(p.num("ron"), 1e-6)
                _stamp_g(A, a, k, g)
                von = p.num("von")
                if a >= 0:
                    b[a] += g * von
                if k >= 0:
                    b[k] -= g * von
        elif kind == "MOS":
            d, g, s = circ.node(pid, "D"), circ.node(pid, "G"), circ.node(pid, "S")
            _stamp_g(A, g, s, 1e-9)
            r = p.num("ron") if mos_on.get(pid) else p.num("roff")
            _stamp_g(A, d, s, 1.0 / max(r, 1e-6))
        elif kind == "IC":
            _stamp_ic(circ, A, b, pid, p, ctrl or {})
        elif kind == "PORT":
            # Connectors are net labels; leakage avoids singular floating data pins.
            for pin in p.spec.pins:
                _stamp_g(A, circ.node(pid, pin), -1, 1e-9)
            continue
        elif kind == "GND":
            continue
        else:
            raise SolveError("unsupported", f"{pid}: componente non simulabile ({p.type})", part=pid)
    return A, b, br


def _solve(A, b):
    try:
        return np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        raise SolveError(
            "singular",
            "matrice singolare: probabilmente un nodo e' isolato o un componente e' aperto")


def _volts(circ, x):
    v = np.zeros(circ.n)
    v[:] = x[:circ.n]
    return v


def _update_leds(circ, x, state):
    out = dict(state)
    for pid, p in circ.parts.items():
        if p.kind not in DIODES:
            continue
        a, k = circ.node(pid, "A"), circ.node(pid, "K")
        v = (x[a] if a >= 0 else 0.0) - (x[k] if k >= 0 else 0.0)
        vf = p.num("vf")
        if not state.get(pid):
            if v > vf + 1e-6:
                out[pid] = True
        else:
            if v < vf - 1e-9:
                out[pid] = False
    return out


def _update_mosfets(circ, x, state):
    out = dict(state)
    for pid, p in circ.parts.items():
        if p.kind != "MOS":
            continue
        g, s = circ.node(pid, "G"), circ.node(pid, "S")
        vgs = (x[g] if g >= 0 else 0.0) - (x[s] if s >= 0 else 0.0)
        vth = p.num("vth")
        if not state.get(pid):
            if vgs > vth + 1e-6:
                out[pid] = True
        else:
            if vgs < vth - 0.2:
                out[pid] = False
    return out


def _update_relays(circ, x, state):
    out = dict(state)
    for pid, p in circ.parts.items():
        if p.kind not in ("RELAY", "RELAY2"):
            continue
        cp, cm = circ.node(pid, "COIL+"), circ.node(pid, "COIL-")
        v = (x[cp] if cp >= 0 else 0.0) - (x[cm] if cm >= 0 else 0.0)
        if not state.get(pid):
            if v > p.num("vpull"):
                out[pid] = True
        else:
            if v < p.num("vdrop"):
                out[pid] = False
    return out


def _update_transistors(circ, x, state):
    out = dict(state)
    for pid, p in circ.by_kind("NPN"):
        c = circ.node(pid, "C")
        b_ = circ.node(pid, "B")
        e = circ.node(pid, "E")
        vbe = (x[b_] if b_ >= 0 else 0.0) - (x[e] if e >= 0 else 0.0)
        vce = (x[c] if c >= 0 else 0.0) - (x[e] if e >= 0 else 0.0)
        vbe_on = p.num("vbe")
        vcesat = p.num("vcesat")
        st = state.get(pid, 0)
        if st == 0:
            if vbe > vbe_on + 1e-6:
                out[pid] = 1
        elif st == 1:
            if vbe < vbe_on - 1e-9:
                out[pid] = 0
            elif vce < vcesat:
                out[pid] = 2
        else:
            if vbe < vbe_on - 1e-9:
                out[pid] = 0
    return out


def _update_puts(circ, x, state):
    out = dict(state)
    for pid, p in circ.by_kind("PUT"):
        a = circ.node(pid, "A")
        g = circ.node(pid, "G")
        k = circ.node(pid, "K")
        va = x[a] if a >= 0 else 0.0
        vg = x[g] if g >= 0 else 0.0
        vk = x[k] if k >= 0 else 0.0
        vf = p.num("vf")
        st = state.get(pid, 0)
        if st == 0:
            if va > vg + vf + 1e-6:
                out[pid] = 1
        else:
            iak = (va - vk - p.num("von")) / max(p.num("ron"), 1e-6)
            if iak < p.num("ihold"):
                out[pid] = 0
    return out


def _pin_v(x, idx):
    return x[idx] if idx >= 0 else 0.0


def _extract(circ, res, x, br, mode, dt, vprev, led_on, relay_on, q_on, mos_on, ctrl, t=0.0):
    v = _volts(circ, x)
    for i, name in enumerate(circ.node_names):
        res.nodes[name] = float(v[i])
    for pid, p in circ.parts.items():
        kind = p.kind
        i = 0.0
        pw = 0.0
        if kind in ("R", "SPK", "LAMP"):
            if kind == "SPK":
                a, c = circ.node(pid, "+"), circ.node(pid, "-")
            else:
                a, c = circ.node(pid, "1"), circ.node(pid, "2")
            r = p.num("r")
            i = (_pin_v(x, a) - _pin_v(x, c)) / r
            pw = i * i * r
        elif kind == "V":
            a, c = circ.node(pid, "+"), circ.node(pid, "-")
            i = -x[br[pid]]
            pw = abs((_pin_v(x, a) - _pin_v(x, c)) * i)
        elif kind == "L":
            i = x[br[pid]]
            pw = 0.0
        elif kind == "XFMR":
            pp, pm = circ.node(pid, "P+"), circ.node(pid, "P-")
            nn = p.num("n")
            ib = x[br[pid]]
            i = -nn * ib
            v1 = _pin_v(x, pp) - _pin_v(x, pm)
            pw = abs(v1 * i)
            res.currents[f"{pid}.2"] = float(-ib)
        elif kind == "C":
            a, c = circ.node(pid, "+"), circ.node(pid, "-")
            if mode == "transient":
                i = p.num("c") / dt * ((_pin_v(x, a) - _pin_v(x, c)) -
                                       (_pin_v(vprev, a) - _pin_v(vprev, c)))
            pw = 0.0
        elif kind in DIODES:
            a, k = circ.node(pid, "A"), circ.node(pid, "K")
            vv = _pin_v(x, a) - _pin_v(x, k)
            i = max(0.0, (vv - p.num("vf")) / max(p.num("rd"), 1e-3)) if led_on.get(pid) else 0.0
            pw = vv * i
        elif kind == "SW":
            a, c = circ.node(pid, "1"), circ.node(pid, "2")
            duty = ctrl.get(pid) if ctrl else None
            r = p.num("ron") if _switch_closed(p, t, mode, duty) else p.num("roff")
            i = (_pin_v(x, a) - _pin_v(x, c)) / max(r, 1e-6)
            pw = i * i * max(r, 1e-6)
        elif kind == "POT":
            a, w = circ.node(pid, "1"), circ.node(pid, "W")
            rt = p.num("rtotal")
            pos = min(max(p.num("pos"), 0.0), 1.0)
            i = (_pin_v(x, a) - _pin_v(x, w)) / max(rt * pos, 1e-6)
            pw = i * i * rt
        elif kind in ("RELAY", "RELAY2"):
            cp, cm = circ.node(pid, "COIL+"), circ.node(pid, "COIL-")
            i = (_pin_v(x, cp) - _pin_v(x, cm)) / max(p.num("rcoil"), 1e-6)
            pw = i * i * p.num("rcoil")
        elif kind == "NPN":
            c, b_, e = circ.node(pid, "C"), circ.node(pid, "B"), circ.node(pid, "E")
            vbe = _pin_v(x, b_) - _pin_v(x, e)
            vce = _pin_v(x, c) - _pin_v(x, e)
            st = q_on.get(pid, 0)
            if st == 0:
                i = 0.0
            elif st == 1:
                i = max(0.0, p.num("beta") * (vbe - p.num("vbe")) / max(p.num("rb"), 1e-3))
            else:
                i = max(0.0, (vce - p.num("vcesat")) / max(p.num("ron"), 1e-6))
            pw = i * vce
        elif kind == "PUT":
            a, k = circ.node(pid, "A"), circ.node(pid, "K")
            vv = _pin_v(x, a) - _pin_v(x, k)
            st = q_on.get(pid, 0)
            i = max(0.0, (vv - p.num("von")) / max(p.num("ron"), 1e-6)) if st else 0.0
            pw = i * vv
        elif kind == "MOS":
            d, g, s = circ.node(pid, "D"), circ.node(pid, "G"), circ.node(pid, "S")
            vds = _pin_v(x, d) - _pin_v(x, s)
            r = p.num("ron") if mos_on.get(pid) else p.num("roff")
            i = vds / max(r, 1e-6)
            pw = abs(vds * i)
        elif kind == "IC":
            state = ctrl or {}
            if p.type == "bq24074":
                if state.get(f"{pid}:input", False):
                    i = (_pin_v(x, circ.node(pid, "IN")) -
                         _pin_v(x, circ.node(pid, "OUT"))) / 0.08
                else:
                    i = (_pin_v(x, circ.node(pid, "BAT")) -
                         _pin_v(x, circ.node(pid, "OUT"))) / 0.12
                pw = abs(i * _pin_v(x, circ.node(pid, "IN")))
            elif p.type == "tps61023":
                if state.get(f"{pid}:enabled", False):
                    i = state.get(f"{pid}:iin", 0.0)
                    pw = i * _pin_v(x, circ.node(pid, "VIN"))
            elif p.type == "tps2553":
                if state.get(f"{pid}:enabled", False) and state.get(f"{pid}:limited", False):
                    i = _tps2553_limit(circ, pid)
                else:
                    resistance = 0.08 if state.get(f"{pid}:enabled", False) else 1e9
                    i = (_pin_v(x, circ.node(pid, "IN")) -
                         _pin_v(x, circ.node(pid, "OUT"))) / resistance
                pw = abs(i * (_pin_v(x, circ.node(pid, "IN")) -
                              _pin_v(x, circ.node(pid, "OUT"))))
            elif p.type == "protection_liion_1s" and state.get(f"{pid}:enabled", False):
                i = (_pin_v(x, circ.node(pid, "B+")) -
                     _pin_v(x, circ.node(pid, "P+"))) / 0.01
                pw = i * i * 0.01
        elif kind == "PORT":
            i = 0.0
            pw = 0.0
        elif kind == "GND":
            i = 0.0
            pw = 0.0
        res.currents[pid] = float(i)
        res.power[pid] = float(abs(pw))
    _violations(circ, res, x, led_on)
    return v


def _violations(circ, res, x, led_on):
    res.violations = []
    for pid, p in circ.parts.items():
        kind = p.kind
        i = res.currents.get(pid, 0.0)
        if kind in DIODES:
            imax = p.get("imax")
            if imax is not None and abs(i) > to_float(imax) * 1.02:
                what = "LED" if kind == "LED" else "diodo"
                res.violations.append({
                    "part": pid, "code": "burned",
                    "message": f"{pid}: {abs(i) * 1e3:.0f} mA superano il massimo di "
                               f"{to_float(imax) * 1e3:.0f} mA, il {what} si brucia",
                    "value": abs(i), "limit": to_float(imax)})
        elif kind in ("R", "SPK"):
            pmax = p.get("pmax")
            if pmax is not None and res.power[pid] > to_float(pmax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "overpower",
                    "message": f"{pid}: {res.power[pid]:.2f} W superano {to_float(pmax)} W, la resistenza si surriscalda",
                    "value": res.power[pid], "limit": to_float(pmax)})
        elif kind == "L":
            imax = p.get("imax")
            if imax is not None and abs(i) > to_float(imax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "overcurrent",
                    "message": f"{pid}: {abs(i) * 1e3:.0f} mA superano il massimo",
                    "value": abs(i), "limit": to_float(imax)})
        elif kind == "C":
            vmax = p.get("vmax")
            a, c = circ.node(pid, "+"), circ.node(pid, "-")
            vv = abs(_pin_v(x, a) - _pin_v(x, c))
            if vmax is not None and vv > to_float(vmax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "overvoltage",
                    "message": f"{pid}: {vv:.1f} V superano i {to_float(vmax)} V, il condensatore si danneggia",
                    "value": vv, "limit": to_float(vmax)})
        elif kind == "NPN":
            imax = p.get("imax")
            if imax is not None and abs(i) > to_float(imax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "overcurrent",
                    "message": f"{pid}: {abs(i) * 1e3:.0f} mA di collettore superano il massimo di "
                               f"{to_float(imax) * 1e3:.0f} mA, il transistor si brucia",
                    "value": abs(i), "limit": to_float(imax)})
        elif kind == "PUT":
            imax = p.get("imax")
            if imax is not None and abs(i) > to_float(imax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "overcurrent",
                    "message": f"{pid}: {abs(i) * 1e3:.0f} mA di anodo superano il massimo di "
                               f"{to_float(imax) * 1e3:.0f} mA, il PUT si brucia",
                    "value": abs(i), "limit": to_float(imax)})
        elif kind == "MOS":
            imax = p.get("imax")
            if imax is not None and abs(i) > to_float(imax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "overcurrent",
                    "message": f"{pid}: {abs(i):.2f} A di drain superano il massimo di "
                               f"{to_float(imax):.2f} A, il MOSFET si brucia",
                    "value": abs(i), "limit": to_float(imax)})
        elif kind == "XFMR":
            imax = p.get("imax")
            ip = abs(res.currents.get(pid, 0.0))
            if imax is not None and ip > to_float(imax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "overcurrent",
                    "message": f"{pid}: {ip * 1e3:.0f} mA al primario superano il massimo di "
                               f"{to_float(imax) * 1e3:.0f} mA, il trasformatore si surriscalda",
                    "value": ip, "limit": to_float(imax)})
            imax2 = p.get("imax2")
            isec = abs(res.currents.get(f"{pid}.2", 0.0))
            if imax2 is not None and isec > to_float(imax2) * 1.02:
                res.violations.append({
                    "part": pid, "code": "overcurrent",
                    "message": f"{pid}: {isec:.2f} A al secondario superano il massimo di "
                               f"{to_float(imax2):.2f} A, il trasformatore si surriscalda",
                    "value": isec, "limit": to_float(imax2)})
        elif kind == "V":
            imax = p.get("imax")
            if imax is not None and abs(i) > to_float(imax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "short",
                    "message": f"{pid}: {abs(i):.1f} A richiesti, cortocircuito",
                    "value": abs(i), "limit": to_float(imax)})


def _dc(circ):
    res = Result(circ, "dc")
    led = {pid: False for pid, p in circ.parts.items() if p.kind in DIODES}
    relay = {pid: False for pid, p in circ.parts.items() if p.kind in ("RELAY", "RELAY2")}
    q = {pid: 0 for pid, p in circ.parts.items() if p.kind in ("NPN", "PUT")}
    mos = {pid: False for pid, p in circ.parts.items() if p.kind == "MOS"}
    models = {}
    seen = set()
    x = None
    br = None
    for it in range(40):
        A, b, br = _build(circ, "dc", 0.0, None, np.zeros(circ.n), {},
                          led, relay, q, mos, models)
        x = _solve(A, b)
        nl = _update_leds(circ, x, led)
        nr = _update_relays(circ, x, relay)
        nq = _update_transistors(circ, x, q)
        nq = _update_puts(circ, x, nq)
        nm = _update_mosfets(circ, x, mos)
        npower = _update_power_models(circ, x, models)
        if (nl == led and nr == relay and nq == q and nm == mos and
                _model_states_equal(npower, models)):
            break
        key = (tuple(sorted((k, v) for k, v in nl.items())),
               tuple(sorted((k, v) for k, v in nr.items())),
               tuple(sorted((k, v) for k, v in nq.items())),
               tuple(sorted((k, v) for k, v in nm.items())),
               tuple(sorted(npower.items())))
        if key in seen:
            res.notes.append("nessun punto di riposo stabile: il circuito oscilla, usa analysis 'transient'")
            break
        seen.add(key)
        led, relay, q, mos = nl, nr, nq, nm
        models = npower
    _extract(circ, res, x, br, "dc", None, np.zeros(circ.n), led, relay, q, mos, models)
    res.relay_states = dict(relay)
    res.residual = float(np.max(np.abs(A @ x - b)))
    return res


def _auto_timing(circ):
    rsum = 0.0
    caps = []
    inds = []
    for pid, p in circ.parts.items():
        k = p.kind
        if k in ("R", "SPK"):
            rsum += p.num("r")
        elif k == "POT":
            rsum += p.num("rtotal")
        elif k in ("RELAY", "RELAY2"):
            rsum += p.num("rcoil")
        elif k in DIODES:
            rsum += p.num("rd")
        elif k == "C":
            caps.append(p.num("c"))
        elif k == "L":
            inds.append(p.num("l"))
    rsum = max(rsum, 0.1)
    taus = [rsum * c for c in caps if c > 0] + [l / rsum for l in inds if l > 0]
    f0s = [1.0 / (2 * math.pi * math.sqrt(l * c))
           for l in inds for c in caps if l > 0 and c > 0]
    dt = min(taus) / 20.0 if taus else 1e-3
    if f0s:
        dt = min(dt, 1.0 / (50.0 * max(f0s)))
    tstop = max([6.0 * max(taus)] if taus else [1e-3])
    if f0s:
        tstop = max(tstop, 20.0 / max(f0s))
    freqs = [to_float(p.get("freq", 50.0)) for pid, p in circ.parts.items()
             if p.kind == "V" and p.get("wave") == "sin"]
    if freqs:
        period = 1.0 / max(freqs)
        dt = min(dt, period / 200.0)
        tstop = max(tstop, 5.0 * period)
    return dt, min(tstop, 120.0)


def _tran(circ):
    dt, tstop = _auto_timing(circ)
    if circ.dt is not None:
        dt = to_float(circ.dt)
    if circ.tstop is not None:
        tstop = to_float(circ.tstop)
    if dt <= 0:
        raise SolveError("bad_value", "dt deve essere positivo")
    nsteps = int(round(tstop / dt))
    if nsteps < 2:
        raise SolveError("bad_value", "tstop troppo breve rispetto a dt")
    if nsteps > 300000:
        raise SolveError("too_long", f"troppi passi ({nsteps}); aumenta dt o riduci tstop", steps=nsteps)

    res = Result(circ, "transient")
    n = circ.n
    vprev = np.zeros(n)
    iprev = {pid: 0.0 for pid, _ in circ.by_kind("L")}
    led = {pid: False for pid, p in circ.parts.items() if p.kind in DIODES}
    relays = [(pid, p) for pid, p in circ.parts.items() if p.kind in ("RELAY", "RELAY2")]
    relay = {pid: False for pid, _ in relays}
    relay_last = {pid: -1e9 for pid, _ in relays}
    q = {pid: 0 for pid, p in circ.parts.items() if p.kind in ("NPN", "PUT")}
    mos = {pid: False for pid, p in circ.parts.items() if p.kind == "MOS"}
    models = {}
    ctrl = {pid: (p.num("duty") if "duty" in p.params else 0.5)
            for pid, p in circ.parts.items()
            if p.kind == "SW" and p.get("vref", 0) > 0 and circ.connected(pid, "FB")}
    ff = {pid for pid in ctrl if circ.connected(pid, "FF")}
    corr = {pid: 0.0 for pid in ff}
    time = np.zeros(nsteps)
    relay_hist = {pid: np.zeros(nsteps) for pid, _ in relays}
    viol_acc = {}

    waves = {f"V({name})": np.zeros(nsteps) for name in circ.node_names}
    for pid in circ.parts:
        waves[f"I({pid})"] = np.zeros(nsteps)
        if circ.part(pid).kind == "XFMR":
            waves[f"I({pid}.2)"] = np.zeros(nsteps)

    for step in range(nsteps):
        t = (step + 1) * dt
        for pid in relay_hist:
            relay_hist[pid][step] = 1.0 if relay[pid] else 0.0
        model_ctrl = {**ctrl, **models}
        A, b, br = _build(circ, "transient", t, dt, vprev, iprev, led, relay,
                          q, mos, model_ctrl)
        x = _solve(A, b)
        for _ in range(8):
            nl = _update_leds(circ, x, led)
            nq = _update_transistors(circ, x, q)
            nq = _update_puts(circ, x, nq)
            nm = _update_mosfets(circ, x, mos)
            npower = _update_power_models(circ, x, models)
            if nl == led and nq == q and nm == mos and _model_states_equal(npower, models):
                break
            led, q, mos = nl, nq, nm
            models = npower
            model_ctrl = {**ctrl, **models}
            A, b, br = _build(circ, "transient", t, dt, vprev, iprev, led, relay,
                              q, mos, model_ctrl)
            x = _solve(A, b)
        res.residual = max(res.residual, float(np.max(np.abs(A @ x - b))))
        v = _extract(circ, res, x, br, "transient", dt, vprev, led, relay,
                     q, mos, model_ctrl, t)
        for pid in ctrl:
            p = circ.part(pid)
            soft = p.num("t_soft") if "t_soft" in p.params else 0.0
            if t < soft:
                continue
            fb = circ.node(pid, "FB")
            vfb = _pin_v(x, fb) if fb >= 0 else 0.0
            err = p.num("vref") - vfb
            ki = p.num("ki") if "ki" in p.params else 0.0
            if pid in ff:
                ffn = circ.node(pid, "FF")
                vff = _pin_v(x, ffn) if ffn >= 0 else 0.0
                dff = p.num("vref") / max(vff, 0.1)
                corr[pid] = min(max(corr[pid] + ki * err * dt, -0.4), 0.4)
                ctrl[pid] = min(max(dff + corr[pid], 0.0), 1.0)
            else:
                ctrl[pid] = min(max(ctrl[pid] + ki * err * dt, 0.0), 1.0)
        for viol in res.violations:
            key = (viol["part"], viol["code"])
            item = dict(viol)
            item["time"] = t
            if key not in viol_acc or abs(item["value"]) > abs(viol_acc[key]["value"]):
                viol_acc[key] = item
        time[step] = t
        for i, name in enumerate(circ.node_names):
            waves[f"V({name})"][step] = v[i]
        for pid in circ.parts:
            waves[f"I({pid})"][step] = res.currents[pid]
            if circ.part(pid).kind == "XFMR":
                waves[f"I({pid}.2)"][step] = res.currents.get(f"{pid}.2", 0.0)
        for pid, p in relays:
            cp, cm = circ.node(pid, "COIL+"), circ.node(pid, "COIL-")
            vc = (_pin_v(x, cp) - _pin_v(x, cm)) if (cp >= 0 or cm >= 0) else 0.0
            td = p.num("td") if "td" in p.params else 0.01
            if t - relay_last[pid] >= td:
                if not relay[pid] and vc > p.num("vpull"):
                    relay[pid] = True
                    relay_last[pid] = t
                elif relay[pid] and vc < p.num("vdrop"):
                    relay[pid] = False
                    relay_last[pid] = t
        vprev = v.copy()
        for pid in iprev:
            iprev[pid] = x[br[pid]]

    res.time = time
    res.waves = waves
    res.relay_states = relay_hist
    res.nodes = {name: float(waves[f"V({name})"][-1]) for name in circ.node_names}
    res.currents = {pid: float(waves[f"I({pid})"][-1]) for pid in circ.parts}
    for pid in circ.parts:
        if circ.part(pid).kind == "XFMR":
            res.currents[f"{pid}.2"] = float(waves[f"I({pid}.2)"][-1])
    _violations(circ, res, x, led)
    res.violations = sorted(viol_acc.values(), key=lambda v: (v["part"], v["code"]))
    return res


def check(circ, res):
    out = []
    expected_viol = circ.expect.get("violations")
    if expected_viol is not None:
        have = sorted({v["part"] for v in res.violations})
        want = sorted(expected_viol)
        out.append({"signal": "violations", "ok": have == want,
                    "detail": f"attesi {want}, ottenuti {have}"})
    for sig, cond in circ.expect.items():
        if sig == "violations":
            continue
        vals = res.value(sig)
        if vals is None:
            out.append({"signal": sig, "ok": False, "detail": "segnale non trovato"})
            continue
        conds = cond if isinstance(cond, list) else [cond]
        ok = True
        details = []
        for c in conds:
            if "at" in c:
                if res.time is None:
                    ok = False
                    details.append("'at' richiede analisi transient")
                else:
                    tq = float(c["at"])
                    val = float(np.interp(tq, res.time, vals))
                    tol = float(c.get("tol", 0.05))
                    exp = float(c["approx"])
                    good = abs(val - exp) <= tol * max(abs(exp), 1e-12)
                    ok = ok and good
                    details.append(f"a {tq:g}s: {val:.4g} (atteso {exp:.4g} +/- {tol * 100:g}%)")
            elif "approx" in c:
                val = float(vals[-1])
                tol = float(c.get("tol", 0.05))
                exp = float(c["approx"])
                good = abs(val - exp) <= tol * max(abs(exp), 1e-12)
                ok = ok and good
                details.append(f"{val:.4g} (atteso {exp:.4g} +/- {tol * 100:g}%)")
            lo = c.get("min")
            hi = c.get("max")
            if lo is not None:
                vmin = float(np.min(vals))
                good = vmin >= float(lo)
                ok = ok and good
                details.append(f"min {vmin:.4g} >= {float(lo):.4g}")
            if hi is not None:
                vmax = float(np.max(vals))
                good = vmax <= float(hi)
                ok = ok and good
                details.append(f"max {vmax:.4g} <= {float(hi):.4g}")
            mean = c.get("mean")
            if mean is not None:
                vmean = float(np.mean(vals))
                tol = float(c.get("mean_tol", c.get("tol", 0.05)))
                good = abs(vmean - float(mean)) <= tol * max(abs(float(mean)), 1e-12)
                ok = ok and good
                details.append(f"media {vmean:.4g} ~ {float(mean):.4g} +/- {tol * 100:g}%")
            pk = c.get("peak_min")
            if pk is not None:
                vmax = float(np.max(vals))
                good = vmax >= float(pk)
                ok = ok and good
                details.append(f"picco {vmax:.4g} >= {float(pk):.4g}")
        out.append({"signal": sig, "ok": ok, "detail": "; ".join(details)})
    res.checks = out
    res.ok = all(c["ok"] for c in out)
    if expected_viol is None and res.violations:
        res.ok = False
    return out
