import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from clab import spice
from clab.circuit import from_dict
from clab.db import DB

ROOT = Path(__file__).resolve().parent.parent
DB_ = DB(ROOT / "data" / "components")
NGSPICE = shutil.which("ngspice")


def load(eid):
    return from_dict(json.loads((ROOT / "data" / "exercises" / f"{eid}.json").read_text()), DB_)


def parse_op(log):
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("Index"):
            headers = line.split()[1:]
            data = lines[i + 2].split()[1:]
            return {h: float(v.replace("e", "e")) for h, v in zip(headers, data)}
    raise AssertionError("tabella .op non trovata")


def parse_meas(log, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*([-+0-9.eE]+)", log)
    if not m:
        raise AssertionError(f"misura {name} non trovata")
    return float(m.group(1))


@unittest.skipUnless(NGSPICE, "ngspice non installato")
class NgspiceTests(unittest.TestCase):
    def run_spice(self, circ, probes=(), meas=()):
        text = spice.netlist(circ, probes=probes, meas=meas)
        with tempfile.TemporaryDirectory() as tmp:
            net = Path(tmp) / "net.cir"
            net.write_text(text)
            proc = subprocess.run([NGSPICE, "-b", str(net)],
                                  cwd=tmp, capture_output=True, text=True, timeout=120)
            out = proc.stdout
            if proc.returncode != 0:
                raise AssertionError(out[-2000:])
            return text, out

    def test_led_dc(self):
        circ = load("exp03")
        _, log = self.run_spice(circ, probes=["v(m)", "i(v1)"])
        values = parse_op(log)
        code = load("exp03")
        from clab.solver import simulate
        ours = simulate(code)
        self.assertAlmostEqual(values["v(m)"], ours.nodes["m"], delta=0.15)
        self.assertAlmostEqual(-values["v1#branch"], ours.currents["D1"], delta=0.002)

    def test_rc_transient(self):
        circ = load("exp09")
        _, log = self.run_spice(circ, meas=[("vm10", "v(m)", 10)])
        vm10 = parse_meas(log, "vm10")
        self.assertAlmostEqual(vm10, 9 * (1 - 2.718281828459045 ** -1), delta=0.05)

    def test_npn_dc(self):
        circ = load("exp10")
        _, log = self.run_spice(circ, probes=["v(c)", "v(m)", "i(v1)"])
        values = parse_op(log)
        from clab.solver import simulate
        ours = simulate(load("exp10"))
        self.assertLess(abs(values["v(c)"] - ours.nodes["c"]) / max(ours.nodes["c"], 1e-9), 0.10)
        self.assertLess(abs(-values["v1#branch"] - ours.currents["V1"]) / max(ours.currents["V1"], 1e-9), 0.15)


if __name__ == "__main__":
    unittest.main()
