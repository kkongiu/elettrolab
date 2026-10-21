import json
import unittest
from pathlib import Path

import numpy as np

from clab.circuit import from_dict
from clab.db import DB
from clab.solver import simulate

ROOT = Path(__file__).resolve().parent.parent
DB_ = DB(ROOT / "data" / "components")


def load(eid):
    data = json.loads((ROOT / "data" / "exercises" / f"{eid}.json").read_text())
    return from_dict(data, DB_)


def run(eid):
    circ = load(eid)
    return simulate(circ)


def npn_circuit(rb="470k", rc="1k", closed=True):
    return from_dict({
        "id": "npn", "title": "npn", "analysis": "dc",
        "parts": {
            "V1": {"type": "supply_12v"},
            "RC": {"type": "resistor", "r": rc},
            "RB": {"type": "resistor", "r": rb},
            "SW1": {"type": "switch_spst", "closed": closed},
            "Q1": {"type": "transistor_npn"},
            "RPD": {"type": "resistor", "r": "100k"},
        },
        "nets": {
            "p": ["V1.+", "RC.1", "RB.1"],
            "c": ["RC.2", "Q1.C"],
            "bb": ["RB.2", "SW1.1"],
            "b": ["SW1.2", "Q1.B", "RPD.1"],
            "gnd": ["V1.-", "Q1.E", "RPD.2"],
        },
    }, DB_)


class PhysicsTests(unittest.TestCase):
    def test_residuals_all_exercises(self):
        for path in sorted((ROOT / "data" / "exercises").glob("*.json")):
            with self.subTest(exercise=path.stem):
                circ = from_dict(json.loads(path.read_text()), DB_)
                res = simulate(circ)
                self.assertLess(res.residual, 1e-8)

    def test_rc_analytic(self):
        res = run("exp09")
        v10 = float(np.interp(10, res.time, res.waves["V(m)"]))
        self.assertAlmostEqual(v10, 9 * (1 - np.exp(-1)), delta=0.03)

    def test_rlc_peak(self):
        res = run("lrc")
        zeta = 0.05
        expected = 5 * (1 + np.exp(-zeta * np.pi / np.sqrt(1 - zeta ** 2)))
        peak = float(res.waves["V(m)"].max())
        self.assertLess(abs(peak - expected) / expected, 0.02)

    def test_npn_cutoff(self):
        res = simulate(npn_circuit(closed=False))
        vbe = res.nodes.get("b", 0.0)
        self.assertLess(abs(vbe), 0.05)
        self.assertLess(abs(res.currents["Q1"]), 1e-6)

    def test_npn_active(self):
        res = simulate(npn_circuit(rb="470k"))
        vbe = res.nodes.get("b", 0.0)
        vce = res.nodes["c"]
        ib = (vbe - 0.7) / 10.0
        ic = res.currents["Q1"]
        self.assertGreater(vce, 5.5)
        self.assertLess(vce, 9.0)
        self.assertGreater(ic, 3.5e-3)
        self.assertLess(ic, 5e-3)
        self.assertAlmostEqual(ic / ib, 240.0, delta=5.0)

    def test_npn_saturation(self):
        res = simulate(npn_circuit(rb="10k"))
        vce = res.nodes["c"]
        ic = res.currents["Q1"]
        self.assertLess(vce, 0.25)
        self.assertGreater(ic, 10e-3)
        self.assertLess(ic, 13e-3)

    def test_put_threshold_and_period(self):
        res = run("exp11")
        vg = res.nodes["g"]
        va = res.waves["V(a)"]
        self.assertAlmostEqual(float(va.max()), vg + 0.6, delta=0.01)
        thr = vg + 0.55
        up = [i for i in range(1, len(va)) if va[i - 1] <= thr <= va[i]]
        self.assertGreaterEqual(len(up), 3)
        period = float(np.mean(np.diff(res.time[up])))
        self.assertGreater(period, 0.95)
        self.assertLess(period, 1.12)

    def test_put_peak_convergence(self):
        peaks = {}
        for dt in (50e-6, 25e-6):
            data = json.loads((ROOT / "data" / "exercises" / "exp11.json").read_text())
            data["dt"] = dt
            res = simulate(from_dict(data, DB_))
            peaks[dt] = float(res.waves["I(D1)"].max())
        rel = abs(peaks[50e-6] - peaks[25e-6]) / peaks[25e-6]
        self.assertLess(rel, 0.10)

    def test_transient_overcurrent_is_detected(self):
        data = json.loads((ROOT / "data" / "exercises" / "exp11.json").read_text())
        data["dt"] = 50e-6
        del data["parts"]["R4"]
        data["nets"]["k"] = ["Q1.K", "D1.A"]
        del data["nets"]["lk"]
        res = simulate(from_dict(data, DB_))
        self.assertGreater(float(res.waves["I(D1)"].max()), 0.03)
        self.assertTrue(any(v["part"] == "D1" and v["code"] == "burned"
                            for v in res.violations))

    def test_exp08_two_leds_alternate(self):
        res = run("exp08")
        d1 = res.waves["I(D1)"]
        d2 = res.waves["I(D2)"]
        self.assertGreater(float(d1.max()), 0.009)
        self.assertGreater(float(d2.max()), 0.009)
        both = (d1 > 0.002) & (d2 > 0.002)
        self.assertLess(int(both.sum()), 5)

    def test_switch_and_source_conservation(self):
        res = run("exp10")
        total = res.currents["R1"] + res.currents["R2"]
        self.assertAlmostEqual(res.currents["V1"], total, delta=1e-9)


if __name__ == "__main__":
    unittest.main()
