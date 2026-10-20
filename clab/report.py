import numpy as np

from .circuit import GROUND
from .units import fmt


def part_voltage(circ, res, pid):
    p = circ.part(pid)
    pins = p.spec.pins
    if len(pins) < 2:
        return None
    if p.kind == "NPN":
        pin_a, pin_b = "C", "E"
    elif p.kind == "PUT":
        pin_a, pin_b = "A", "K"
    else:
        pin_a, pin_b = pins[0], pins[1]
    net_a, net_b = circ.net_of(pid, pin_a), circ.net_of(pid, pin_b)
    if net_a is None or net_b is None:
        return None
    va = 0.0 if net_a in GROUND else res.nodes.get(net_a, 0.0)
    vb = 0.0 if net_b in GROUND else res.nodes.get(net_b, 0.0)
    return va - vb


def ascii_plot(t, y, width=64, height=14, label=""):
    y = np.asarray(y, dtype=float)
    t = np.asarray(t, dtype=float)
    n = len(y)
    if n == 0:
        return ""
    lo, hi = float(np.min(y)), float(np.max(y))
    if hi - lo < 1e-12:
        hi = lo + 1e-12
    grid = [[" "] * width for _ in range(height)]
    for col in range(width):
        i0 = int(col * n / width)
        i1 = max(i0 + 1, int((col + 1) * n / width))
        seg = y[i0:i1]
        r_top = int(round((hi - float(np.max(seg))) / (hi - lo) * (height - 1)))
        r_bot = int(round((hi - float(np.min(seg))) / (hi - lo) * (height - 1)))
        for r in range(min(r_top, r_bot), max(r_top, r_bot) + 1):
            grid[r][col] = "|"
    lines = []
    for r in range(height):
        if r == 0:
            lab = fmt(hi, "", 3)
        elif r == height - 1:
            lab = fmt(lo, "", 3)
        elif r == height // 2:
            lab = fmt((hi + lo) / 2, "", 3)
        else:
            lab = ""
        lines.append(f"{lab:>9} |{''.join(grid[r])}")
    lines.append(f"{'':>9} +" + "-" * width)
    lines.append(f"{'':>10}{fmt(t[0], 's', 3):<30}{fmt(t[-1], 's', 3):>34}")
    if label:
        lines.insert(0, f"  {label}")
    return "\n".join(lines)


def print_result(circ, res, plot=None, csv=None):
    print()
    print(f"=== {circ.id} - {circ.title} ===")
    if circ.ref:
        print(circ.ref)
    if circ.notes:
        print(circ.notes)
    print()
    if res.analysis == "dc":
        print("Analisi: punto di riposo (DC)")
    else:
        dt = res.time[1] - res.time[0] if len(res.time) > 1 else 0
        print(f"Analisi: transitorio, {len(res.time)} punti, "
              f"dt = {fmt(dt, 's')}, durata = {fmt(res.time[-1], 's')}")

    if res.notes:
        for n in res.notes:
            print(f"  ! {n}")

    if res.violations:
        print()
        print("VIOLAZIONI")
        for v in res.violations:
            print(f"  x {v['message']}")

    print()
    if res.analysis == "dc":
        if res.nodes:
            print("Nodo        Tensione")
            for name in circ.node_names:
                print(f"  {name:<10} {fmt(res.nodes[name], 'V'):>12}")
        print()
        print(f"{'Componente':<11}{'Tipo':<17}{'Corrente':>11}{'Tensione':>11}{'Potenza':>11}")
        for pid, p in circ.parts.items():
            v = part_voltage(circ, res, pid)
            print(f"{pid:<11}{p.name:<17}{fmt(res.currents[pid], 'A'):>11}"
                  f"{fmt(v, 'V'):>11}{fmt(res.power[pid], 'W'):>11}")
    else:
        print(f"{'Segnale':<10}{'min':>12}{'max':>12}{'finale':>12}")
        for sig, arr in res.waves.items():
            print(f"{sig:<10}{fmt(float(arr.min()), '', 4):>12}"
                  f"{fmt(float(arr.max()), '', 4):>12}"
                  f"{fmt(float(arr[-1]), '', 4):>12}")
        sig = _choose_signal(res, plot)
        if sig and sig in res.waves:
            print()
            print(ascii_plot(res.time, res.waves[sig], label=f"{sig} nel tempo"))

    if res.checks:
        print()
        print("Controlli")
        for c in res.checks:
            mark = "OK  " if c["ok"] else "FAIL"
            print(f"  {mark} {c['signal']}: {c['detail']}")

    if csv and res.time is not None:
        cols = ["time"] + list(res.waves)
        arrs = [res.time] + [res.waves[k] for k in res.waves]
        data = np.column_stack(arrs)
        np.savetxt(csv, data, delimiter=",", header=",".join(cols), comments="")
        print()
        print(f"CSV scritto: {csv}")


def _choose_signal(res, plot):
    if plot:
        return plot
    if not res.waves:
        return None
    node_sigs = [s for s in res.waves if s.startswith("V(")]
    cands = node_sigs or list(res.waves)
    best, best_range = None, -1.0
    for s in cands:
        arr = res.waves[s]
        rng = float(arr.max() - arr.min())
        if rng > best_range:
            best, best_range = s, rng
    return best


def print_catalog(db):
    print(f"{'id':<16}{'nome':<20}{'pin':<24}note")
    for spec in db.types.values():
        print(f"{spec.id:<16}{spec.name:<20}{','.join(spec.pins):<24}{spec.learn[:60]}")
