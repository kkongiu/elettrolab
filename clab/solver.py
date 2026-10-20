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
    raise SolveError("bad_analysis", f"analisi non supportata: {circ.analysis!r}")


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


def _switch_closed(p, t, mode):
    closed = bool(p.get("closed", True))
    if mode == "dc":
        return closed
    if "t_close" in p.params and t >= p.num("t_close"):
        closed = True
    if "t_open" in p.params and t >= p.num("t_open"):
        closed = False
    return closed


def _build(circ, mode, t, dt, vprev, iprev, led_on, relay_on, q_on):
    n = circ.n
    N = n + circ.n_branches
    A = np.zeros((N, N))
    b = np.zeros(N)
    br = {}
    for pid, p in circ.parts.items():
        if p.kind in ("V", "L"):
            br[pid] = n + len(br)

    for pid, p in circ.parts.items():
        kind = p.kind
        if kind == "R":
            a, c = circ.node(pid, "1"), circ.node(pid, "2")
            r = p.num("r")
            if r <= 0:
                raise SolveError("bad_value", f"{pid}: resistenza non positiva", part=pid)
            _stamp_g(A, a, c, 1.0 / r)
        elif kind == "V":
            a, c = circ.node(pid, "+"), circ.node(pid, "-")
            _branch(circ, A, b, br[pid], a, c, p.num("v"))
        elif kind == "L":
            a, c = circ.node(pid, "1"), circ.node(pid, "2")
            l = p.num("l")
            if mode == "dc" or l <= 0:
                _branch(circ, A, b, br[pid], a, c, 0.0)
            else:
                req = l / dt
                _branch(circ, A, b, br[pid], a, c, 0.0, req=req, hist=iprev.get(pid, 0.0))
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
        elif kind == "LED":
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
            r = p.num("ron") if _switch_closed(p, t, mode) else p.num("roff")
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
                _stamp_g(A, a, k, 1.0 / max(p.num("ron"), 1e-6))
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
    for pid, p in circ.by_kind("LED"):
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
            iak = (va - vk) / max(p.num("ron"), 1e-6)
            if iak < p.num("ihold"):
                out[pid] = 0
    return out


def _pin_v(x, idx):
    return x[idx] if idx >= 0 else 0.0


def _extract(circ, res, x, br, mode, dt, vprev, led_on, relay_on, q_on, t=0.0):
    v = _volts(circ, x)
    for i, name in enumerate(circ.node_names):
        res.nodes[name] = float(v[i])
    for pid, p in circ.parts.items():
        kind = p.kind
        i = 0.0
        pw = 0.0
        if kind == "R":
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
        elif kind == "C":
            a, c = circ.node(pid, "+"), circ.node(pid, "-")
            if mode == "transient":
                i = p.num("c") / dt * ((_pin_v(x, a) - _pin_v(x, c)) -
                                       (_pin_v(vprev, a) - _pin_v(vprev, c)))
            pw = 0.0
        elif kind == "LED":
            a, k = circ.node(pid, "A"), circ.node(pid, "K")
            vv = _pin_v(x, a) - _pin_v(x, k)
            i = max(0.0, (vv - p.num("vf")) / max(p.num("rd"), 1e-3)) if led_on.get(pid) else 0.0
            pw = vv * i
        elif kind == "SW":
            a, c = circ.node(pid, "1"), circ.node(pid, "2")
            r = p.num("ron") if _switch_closed(p, t, mode) else p.num("roff")
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
            i = vv / max(p.num("ron"), 1e-6) if st else 0.0
            pw = i * vv
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
        if kind == "LED":
            imax = p.get("imax")
            if imax is not None and abs(i) > to_float(imax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "burned",
                    "message": f"{pid}: {abs(i) * 1e3:.0f} mA superano il massimo di "
                               f"{to_float(imax) * 1e3:.0f} mA, il LED si brucia",
                    "value": abs(i), "limit": to_float(imax)})
        elif kind == "R":
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
        elif kind == "V":
            imax = p.get("imax")
            if imax is not None and abs(i) > to_float(imax) * 1.02:
                res.violations.append({
                    "part": pid, "code": "short",
                    "message": f"{pid}: {abs(i):.1f} A richiesti, cortocircuito",
                    "value": abs(i), "limit": to_float(imax)})


def _dc(circ):
    res = Result(circ, "dc")
    led = {pid: False for pid, _ in circ.by_kind("LED")}
    relay = {pid: False for pid, p in circ.parts.items() if p.kind in ("RELAY", "RELAY2")}
    q = {pid: 0 for pid, p in circ.parts.items() if p.kind in ("NPN", "PUT")}
    seen = set()
    x = None
    br = None
    for it in range(40):
        A, b, br = _build(circ, "dc", 0.0, None, np.zeros(circ.n), {}, led, relay, q)
        x = _solve(A, b)
        nl = _update_leds(circ, x, led)
        nr = _update_relays(circ, x, relay)
        nq = _update_transistors(circ, x, q)
        nq = _update_puts(circ, x, nq)
        if nl == led and nr == relay and nq == q:
            break
        key = (tuple(sorted((k, v) for k, v in nl.items())),
               tuple(sorted((k, v) for k, v in nr.items())),
               tuple(sorted((k, v) for k, v in nq.items())))
        if key in seen:
            res.notes.append("nessun punto di riposo stabile: il circuito oscilla, usa analysis 'transient'")
            break
        seen.add(key)
        led, relay, q = nl, nr, nq
    _extract(circ, res, x, br, "dc", None, np.zeros(circ.n), led, relay, q)
    res.relay_states = dict(relay)
    return res


def _auto_timing(circ):
    rsum = 0.0
    caps = []
    inds = []
    for pid, p in circ.parts.items():
        k = p.kind
        if k == "R":
            rsum += p.num("r")
        elif k == "POT":
            rsum += p.num("rtotal")
        elif k in ("RELAY", "RELAY2"):
            rsum += p.num("rcoil")
        elif k == "LED":
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
    led = {pid: False for pid, _ in circ.by_kind("LED")}
    relays = [(pid, p) for pid, p in circ.parts.items() if p.kind in ("RELAY", "RELAY2")]
    relay = {pid: False for pid, _ in relays}
    relay_last = {pid: -1e9 for pid, _ in relays}
    q = {pid: 0 for pid, p in circ.parts.items() if p.kind in ("NPN", "PUT")}
    time = np.zeros(nsteps)
    relay_hist = {pid: np.zeros(nsteps) for pid, _ in relays}

    waves = {f"V({name})": np.zeros(nsteps) for name in circ.node_names}
    for pid in circ.parts:
        waves[f"I({pid})"] = np.zeros(nsteps)

    for step in range(nsteps):
        t = (step + 1) * dt
        for pid in relay_hist:
            relay_hist[pid][step] = 1.0 if relay[pid] else 0.0
        A, b, br = _build(circ, "transient", t, dt, vprev, iprev, led, relay, q)
        x = _solve(A, b)
        for _ in range(4):
            nl = _update_leds(circ, x, led)
            nq = _update_transistors(circ, x, q)
            nq = _update_puts(circ, x, nq)
            if nl == led and nq == q:
                break
            led, q = nl, nq
            A, b, br = _build(circ, "transient", t, dt, vprev, iprev, led, relay, q)
            x = _solve(A, b)
        v = _extract(circ, res, x, br, "transient", dt, vprev, led, relay, q, t)
        time[step] = t
        for i, name in enumerate(circ.node_names):
            waves[f"V({name})"][step] = v[i]
        for pid in circ.parts:
            waves[f"I({pid})"][step] = res.currents[pid]
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
    _violations(circ, res, x, led)
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
        ok = True
        details = []
        if "at" in cond:
            if res.time is None:
                ok = False
                details.append("'at' richiede analisi transient")
            else:
                tq = float(cond["at"])
                val = float(np.interp(tq, res.time, vals))
                tol = float(cond.get("tol", 0.05))
                exp = float(cond["approx"])
                good = abs(val - exp) <= tol * max(abs(exp), 1e-12)
                ok = ok and good
                details.append(f"a {tq:g}s: {val:.4g} (atteso {exp:.4g} +/- {tol * 100:g}%)")
        elif "approx" in cond:
            val = float(vals[-1])
            tol = float(cond.get("tol", 0.05))
            exp = float(cond["approx"])
            good = abs(val - exp) <= tol * max(abs(exp), 1e-12)
            ok = ok and good
            details.append(f"{val:.4g} (atteso {exp:.4g} +/- {tol * 100:g}%)")
        lo = cond.get("min")
        hi = cond.get("max")
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
        out.append({"signal": sig, "ok": ok, "detail": "; ".join(details)})
    res.checks = out
    res.ok = all(c["ok"] for c in out)
    if expected_viol is None and res.violations:
        res.ok = False
    return out
