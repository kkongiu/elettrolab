import argparse
import json
import os
import sys
from pathlib import Path

from . import report
from .circuit import CircuitError, from_dict
from .db import DB, DBError
from .solver import SolveError, check, simulate
from .units import fmt

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _db():
    return DB(DATA / "components")


def exercise_ids():
    return sorted(p.stem for p in (DATA / "exercises").glob("*.json"))


def load_raw(eid):
    path = DATA / "exercises" / f"{eid}.json"
    if not path.exists():
        raise SystemExit(f"esercizio non trovato: {eid}\nDisponibili: {', '.join(exercise_ids())}")
    return json.loads(path.read_text(encoding="utf-8"))


def _cast(v):
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    return v


def apply_set(raw, expr):
    if "=" not in expr or "." not in expr.split("=", 1)[0]:
        raise SystemExit(f"--set non valido: {expr!r} (usa PID.param=valore)")
    key, val = expr.split("=", 1)
    pid, param = key.split(".", 1)
    if pid not in raw.get("parts", {}):
        raise SystemExit(f"--set: componente {pid!r} non presente in {raw.get('id')}")
    raw["parts"][pid][param] = _cast(val)


def _build(args):
    raw = load_raw(args.id)
    for expr in getattr(args, "overrides", []) or []:
        apply_set(raw, expr)
    return from_dict(raw, _db())


def cmd_list(args):
    print(f"{'id':<10}{'analisi':<12}titolo")
    for eid in exercise_ids():
        raw = load_raw(eid)
        print(f"{raw.get('id', eid):<10}{raw.get('analysis', 'dc'):<12}{raw.get('title', '')}")


def cmd_run(args):
    try:
        circ = _build(args)
        res = simulate(circ)
    except (CircuitError, DBError, SolveError) as e:
        print(f"ERRORE: {e}")
        if hasattr(e, "as_dict"):
            print(json.dumps(e.as_dict(), ensure_ascii=False))
        return 2
    check(circ, res)
    report.print_result(circ, res, plot=args.plot, csv=args.csv)
    if args.strict and not res.ok:
        return 1
    return 0


def cmd_show(args):
    try:
        circ = _build(args)
    except (CircuitError, DBError) as e:
        print(f"ERRORE: {e}")
        return 2
    print(f"{circ.id} - {circ.title}")
    if circ.ref:
        print(circ.ref)
    if circ.notes:
        print(circ.notes)
    print()
    print(f"{'Componente':<11}{'Tipo':<17}valori")
    for pid, p in circ.parts.items():
        vals = {k: v for k, v in p.params.items()}
        print(f"{pid:<11}{p.type:<17}{vals}")
    print()
    print("Reti")
    for net, pins in circ.nets.items():
        tag = "  (gnd)" if net in ("gnd", "0", "GND") else ""
        print(f"  {net:<8} {', '.join(pins)}{tag}")
    print()
    print(f"Analisi: {circ.analysis}")
    if circ.expect:
        print(f"Attese: {json.dumps(circ.expect, ensure_ascii=False)}")
    print()
    print("Note componenti")
    for pid, p in circ.parts.items():
        if p.spec.learn:
            print(f"  {pid} ({p.name}): {p.spec.learn}")
    return 0


def cmd_check(args):
    bad = 0
    print(f"{'esercizio':<10}{'esito':<7}dettagli")
    for eid in exercise_ids():
        try:
            raw = load_raw(eid)
            circ = from_dict(raw, _db())
            res = simulate(circ)
            check(circ, res)
        except (CircuitError, DBError, SolveError) as e:
            print(f"{eid:<10}{'ERROR':<7}{e}")
            bad += 1
            continue
        status = "PASS" if res.ok else "FAIL"
        if not res.ok:
            bad += 1
        details = "; ".join(f"{c['signal']}: {c['detail']}" for c in res.checks)
        if res.violations:
            details += " | " + "; ".join(v["message"] for v in res.violations)
        print(f"{eid:<10}{status:<7}{details}")
    print()
    print(f"{len(exercise_ids()) - bad}/{len(exercise_ids())} esercizi superati")
    return 0 if bad == 0 else 1


def cmd_sweep(args):
    if "=" not in args.sweep:
        raise SystemExit("usa --sweep PID.param=v1,v2,...")
    key, values = args.sweep.split("=", 1)
    print(f"{'valore':<12}{'segnale':<10}{'finale':>12}{'esito':>8}")
    for val in values.split(","):
        try:
            raw = load_raw(args.id)
            apply_set(raw, f"{key}={val}")
            circ = from_dict(raw, _db())
            res = simulate(circ)
        except (CircuitError, DBError, SolveError) as e:
            print(f"{val:<12}{'-':<10}{'-':>12}{'ERROR':>8}  {e}")
            continue
        sig = args.plot or ("I(D1)" if "I(D1)" in res.waves or "D1" in res.currents else next(iter(res.waves), None))
        if sig is None:
            continue
        vals = res.value(sig)
        final = float(vals[-1]) if vals is not None else float("nan")
        note = "violazione" if res.violations else "ok"
        print(f"{val:<12}{sig:<10}{fmt(final, 'A', 4):>12}{note:>8}")
    return 0


def cmd_db(args):
    report.print_catalog(_db())
    return 0


def cmd_gui(args):
    from .gui import main as gui_main
    gui_main(args.id)
    return 0


def cmd_menu(args):
    ids = exercise_ids()
    while True:
        print()
        print("Laboratorio di elettronica")
        print("-" * 58)
        for i, eid in enumerate(ids, 1):
            raw = load_raw(eid)
            print(f"{i:3d}. {eid:<8} {raw.get('title', '')}")
        print("  0. esci")
        try:
            s = input("\nScegli un esercizio: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if s in ("", "0", "q"):
            return 0
        if not s.isdigit() or not (1 <= int(s) <= len(ids)):
            print("scelta non valida")
            continue
        eid = ids[int(s) - 1]
        ns = argparse.Namespace(id=eid, overrides=[], plot=None, csv=None, strict=False)
        try:
            cmd_run(ns)
        except SystemExit:
            pass
        try:
            input("\nInvio per tornare al menu...")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0


def cmd_mcp(args):
    venv = ROOT / ".venv" / "bin" / "python"
    if venv.exists():
        exe = str(venv)
    else:
        try:
            import mcp  # noqa: F401
        except ImportError:
            print("Server MCP non disponibile: crea .venv e installa 'mcp'.")
            print("  python3 -m venv .venv")
            print("  .venv/bin/pip install mcp")
            return 2
        exe = sys.executable
    os.chdir(ROOT)
    os.execv(exe, [exe, "-m", "clab_mcp"])


def cmd_test(args):
    import unittest
    suite = unittest.TestLoader().discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def cmd_selftest(args):
    tests = [
        ("partitore 1k/1k", _test_divider),
        ("LED 9V 470 ohm", _test_led),
        ("RC 10k 1000u a 10 s", _test_rc),
        ("RLC serie: picco", _test_rlc),
        ("LED senza resistenza si brucia", _test_burn),
        ("NPN in zona attiva: amplificazione", _test_transistor),
        ("PUT: oscillatore a rilassamento", _test_put),
    ]
    ok = 0
    for name, fn in tests:
        try:
            good, detail = fn()
        except Exception as e:
            good, detail = False, f"eccezione: {e}"
        print(f"  {'OK  ' if good else 'FAIL'} {name}: {detail}")
        ok += bool(good)
    print(f"\n{ok}/{len(tests)} test superati")
    return 0 if ok == len(tests) else 1


def _c(parts, nets, analysis="dc", **kw):
    data = {"id": "test", "title": "test", "analysis": analysis, "parts": parts, "nets": nets}
    data.update(kw)
    return from_dict(data, _db())


def _test_divider():
    circ = _c({"V1": {"type": "battery_9v"},
               "R1": {"type": "resistor", "r": "1k"},
               "R2": {"type": "resistor", "r": "1k"}},
              {"p": ["V1.+", "R1.1"], "m": ["R1.2", "R2.1"], "gnd": ["V1.-", "R2.2"]})
    res = simulate(circ)
    v = res.nodes["m"]
    return abs(v - 4.5) < 1e-6, f"V(m) = {fmt(v, 'V')} (atteso 4.5 V)"


def _test_led():
    circ = _c({"V1": {"type": "battery_9v"},
               "R1": {"type": "resistor", "r": "470"},
               "D1": {"type": "led_red"}},
              {"p": ["V1.+", "R1.1"], "m": ["R1.2", "D1.A"], "gnd": ["V1.-", "D1.K"]})
    res = simulate(circ)
    i = res.currents["D1"]
    return abs(i - 0.015) < 1e-4, f"I(D1) = {fmt(i, 'A')} (atteso 15 mA)"


def _test_rc():
    circ = _c({"V1": {"type": "battery_9v"},
               "R1": {"type": "resistor", "r": "10k"},
               "C1": {"type": "capacitor", "c": "1000u"}},
              {"p": ["V1.+", "R1.1"], "m": ["R1.2", "C1.+"], "gnd": ["V1.-", "C1.-"]},
              analysis="transient", tstop=10, dt=0.01)
    res = simulate(circ)
    v = res.nodes["m"]
    return abs(v - 5.686) < 0.05, f"V(m) a 10 s = {fmt(v, 'V')} (atteso 5.69 V)"


def _test_rlc():
    circ = _c({"V1": {"type": "battery_9v", "v": 5},
               "R1": {"type": "resistor", "r": 10},
               "L1": {"type": "inductor", "l": 1},
               "C1": {"type": "capacitor", "c": "100u"}},
              {"p": ["V1.+", "R1.1"], "b": ["R1.2", "L1.1"],
               "m": ["L1.2", "C1.+"], "gnd": ["V1.-", "C1.-"]},
              analysis="transient", tstop=0.5, dt=0.0001)
    res = simulate(circ)
    peak = float(res.waves["V(m)"].max())
    return 8.5 < peak < 9.6, f"picco V(m) = {fmt(peak, 'V')} (atteso ~9.27 V)"


def _test_burn():
    circ = _c({"V1": {"type": "battery_9v"}, "D1": {"type": "led_red"}},
              {"p": ["V1.+", "D1.A"], "gnd": ["V1.-", "D1.K"]})
    res = simulate(circ)
    return any(v["part"] == "D1" and v["code"] == "burned" for v in res.violations), \
        f"I(D1) = {fmt(res.currents['D1'], 'A')}, violazioni: {[v['code'] for v in res.violations]}"


def _test_transistor():
    circ = _c({"V1": {"type": "supply_12v"},
               "R1": {"type": "resistor", "r": "1k"},
               "R2": {"type": "resistor", "r": "1M"},
               "Q1": {"type": "transistor_npn"}},
              {"p": ["V1.+", "R1.1", "R2.1"],
               "c": ["R1.2", "Q1.C"],
               "b": ["R2.2", "Q1.B"],
               "gnd": ["V1.-", "Q1.E"]})
    res = simulate(circ)
    ic = res.currents["Q1"]
    return abs(ic - 0.00271) < 5e-5, \
        f"I(Q1) = {fmt(ic, 'A')} (atteso ~2.71 mA con beta=240)"


def _test_put():
    circ = _c({"V1": {"type": "supply_6v"},
               "R1": {"type": "resistor", "r": "470k"},
               "R2": {"type": "resistor", "r": "15k"},
               "R3": {"type": "resistor", "r": "27k"},
               "C1": {"type": "capacitor", "c": "2.2u"},
               "Q1": {"type": "put"},
               "R4": {"type": "resistor", "r": "100"},
               "D1": {"type": "led_red"}},
              {"p": ["V1.+", "R1.1", "R2.1"],
               "a": ["R1.2", "Q1.A", "C1.+"],
               "g": ["R2.2", "R3.1", "Q1.G"],
               "k": ["Q1.K", "R4.1"],
               "lk": ["R4.2", "D1.A"],
               "gnd": ["V1.-", "R3.2", "C1.-", "D1.K"]},
              analysis="transient", tstop=4, dt=0.00005)
    res = simulate(circ)
    peak = float(res.waves["I(D1)"].max())
    return 0.012 < peak < 0.018 and not res.violations, \
        f"I(D1) picco = {fmt(peak, 'A')} (con R4, nessuna violazione)"


def main(argv=None):
    p = argparse.ArgumentParser(prog="clab", description="Laboratorio di elettronica didattico")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="elenca gli esercizi")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("run", help="simula un esercizio")
    s.add_argument("id")
    s.add_argument("--set", dest="overrides", action="append", default=[],
                   help="modifica un parametro, es. --set R1.r=2k")
    s.add_argument("--plot", help="segnale da graficare, es. V(m); 'none' per nessuno")
    s.add_argument("--csv", help="esporta le forme d'onda in CSV")
    s.add_argument("--strict", action="store_true", help="esce con errore se i controlli falliscono")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("sweep", help="varia un parametro su piu' valori")
    s.add_argument("id")
    s.add_argument("--sweep", required=True, help="PID.param=v1,v2,...")
    s.add_argument("--plot", help="segnale da riportare")
    s.set_defaults(fn=cmd_sweep)

    s = sub.add_parser("show", help="mostra componenti e reti")
    s.add_argument("id")
    s.add_argument("--set", dest="overrides", action="append", default=[])
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("check", help="esegue tutti gli esercizi e verifica le attese")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("db", help="elenca il catalogo componenti")
    s.set_defaults(fn=cmd_db)

    s = sub.add_parser("menu", help="menu interattivo degli esercizi")
    s.set_defaults(fn=cmd_menu)

    s = sub.add_parser("gui", help="visualizzatore grafico degli esercizi")
    s.add_argument("id", nargs="?")
    s.set_defaults(fn=cmd_gui)

    s = sub.add_parser("selftest", help="verifica il motore di simulazione")
    s.set_defaults(fn=cmd_selftest)

    s = sub.add_parser("test", help="esegue i test unitari del progetto")
    s.set_defaults(fn=cmd_test)

    s = sub.add_parser("mcp", help="avvia il server MCP su stdio")
    s.set_defaults(fn=cmd_mcp)

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
