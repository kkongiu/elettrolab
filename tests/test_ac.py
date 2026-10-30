import unittest
import json
from pathlib import Path

from clab.circuit import from_dict
from clab.db import DB
from clab.solver import SolveError, ac_sweep

ROOT = Path(__file__).resolve().parent.parent
DB_ = DB(ROOT / "data" / "components")


def low_pass():
    return from_dict({
        "id": "rc_low_pass",
        "parts": {
            "V1": {"type": "battery_9v"},
            "R1": {"type": "resistor", "r": 1000},
            "C1": {"type": "capacitor", "c": 1e-6},
        },
        "nets": {
            "in": ["V1.+", "R1.1"],
            "out": ["R1.2", "C1.+"],
            "gnd": ["V1.-", "C1.-"],
        },
    }, DB_)


class ACSweepTests(unittest.TestCase):
    def test_rc_low_pass_at_cutoff(self):
        cutoff = 1 / (2 * 3.141592653589793 * 1000 * 1e-6)
        result = ac_sweep(low_pass(), "V1", "out", cutoff / 10, cutoff * 10, 101)
        index = min(range(len(result["frequency"])),
                    key=lambda i: abs(result["frequency"][i] - cutoff))
        self.assertAlmostEqual(result["magnitude_db"][index], -3.0103, delta=0.15)
        self.assertAlmostEqual(result["phase_deg"][index], -45.0, delta=2.0)

    def test_invalid_input_and_nonlinear_parts_report_errors(self):
        with self.assertRaises(SolveError) as err:
            ac_sweep(low_pass(), "V1", "out", 10, 10, 50)
        self.assertEqual(err.exception.code, "bad_frequency")

        circuit = json.loads((ROOT / "data" / "exercises" / "exp03.json").read_text())
        with self.assertRaises(SolveError) as err:
            ac_sweep(from_dict(circuit, DB_), "V1", "m", 1, 1000, 11)
        self.assertEqual(err.exception.code, "unsupported_ac")


if __name__ == "__main__":
    unittest.main()
