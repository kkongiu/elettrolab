import re

from .circuit import GROUND

MODELS = {
    "LED": ".model DLED D(Is=1e-12 N=3 Rs=10)",
    "NPN": ".model QNPN NPN(Is=1e-14 Bf=240 Vaf=100 Rb=10)",
}
PREFIX = {"R": "R", "C": "C", "L": "L", "V": "V", "LED": "D", "NPN": "Q", "SW": "R"}


def device_name(kind, pid):
    pre = PREFIX[kind]
    if pid and pid[0].upper() == pre:
        return pid
    return f"{pre}_{pid}"


def node_name(circ, net):
    if net in GROUND:
        return "0"
    s = re.sub(r"[^A-Za-z0-9_]", "_", net or "n")
    if not s or s[0].isdigit():
        s = "n_" + s
    return s


def netlist(circ, probes=(), meas=(), dt=None, tstop=None):
    lines = [f"* {circ.id} - elettrolab"]
    used = set()
    for pid, p in circ.parts.items():
        kind = p.kind

        def nn(pin):
            return node_name(circ, circ.net_of(pid, pin))

        if kind == "R":
            lines.append(f"{device_name(kind, pid)} {nn('1')} {nn('2')} {p.num('r'):.12g}")
        elif kind == "C":
            lines.append(f"{device_name(kind, pid)} {nn('+')} {nn('-')} {p.num('c'):.12g} IC=0")
        elif kind == "L":
            lines.append(f"{device_name(kind, pid)} {nn('1')} {nn('2')} {p.num('l'):.12g} IC=0")
        elif kind == "V":
            lines.append(f"{device_name(kind, pid)} {nn('+')} {nn('-')} DC {p.num('v'):.12g}")
        elif kind == "SW":
            closed = bool(p.get("closed", True))
            r = p.num("ron") if closed else p.num("roff")
            lines.append(f"{device_name(kind, pid)} {nn('1')} {nn('2')} {r:.12g}")
        elif kind == "LED":
            lines.append(f"{device_name(kind, pid)} {nn('A')} {nn('K')} DLED")
            used.add("LED")
        elif kind == "NPN":
            lines.append(f"{device_name(kind, pid)} {nn('C')} {nn('B')} {nn('E')} QNPN")
            used.add("NPN")
        else:
            raise ValueError(f"spice: componente {pid} ({p.type}) non supportato")
    for model in sorted(used):
        lines.append(MODELS[model])

    transient = circ.analysis == "transient" or bool(meas)
    if transient:
        if dt is None:
            dt = float(circ.dt) if circ.dt is not None else 1e-3
        if tstop is None:
            tstop = float(circ.tstop) if circ.tstop is not None else 10.0
        lines.append(f".tran {float(dt):.12g} {float(tstop):.12g} UIC")
        for name, probe, at in meas:
            lines.append(f".meas tran {name} find {probe} at={float(at):.12g}")
    else:
        lines.append(".op")
        if probes:
            lines.append(".print op " + " ".join(probes))
    lines.append(".end")
    return "\n".join(lines) + "\n"
