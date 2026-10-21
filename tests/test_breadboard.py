import copy
import json
import unittest
from pathlib import Path

from clab.breadboards import BREADBOARDS, hole_xy, validate_layout
from clab.circuit import from_dict
from clab.db import DB

ROOT = Path(__file__).resolve().parent.parent
DB_ = DB(ROOT / "data" / "components")


def load(eid):
    data = json.loads((ROOT / "data" / "exercises" / f"{eid}.json").read_text())
    return from_dict(data, DB_)


class BreadboardTests(unittest.TestCase):
    def test_geometry(self):
        self.assertEqual(hole_xy("A5"), (196, 120))
        self.assertEqual(hole_xy("T+1"), (100, 62))
        with self.assertRaises(ValueError):
            hole_xy("Z1")

    def test_all_layouts_are_electrically_valid(self):
        for eid, layout in BREADBOARDS.items():
            with self.subTest(exercise=eid):
                errors = validate_layout(load(eid), layout)
                self.assertEqual(errors, [])

    def test_missing_wire_is_detected(self):
        layout = copy.deepcopy(BREADBOARDS["exp03"])
        layout["wires"] = [w for w in layout["wires"] if w["net"] != "m"]
        errors = validate_layout(load("exp03"), layout)
        self.assertTrue(any(e["code"] == "open_net" and e.get("net") == "m" for e in errors))

    def test_short_is_detected(self):
        layout = copy.deepcopy(BREADBOARDS["exp03"])
        layout["wires"].append({"net": "m", "points": ["A10", "A16"]})
        errors = validate_layout(load("exp03"), layout)
        self.assertTrue(any(e["code"] == "short" for e in errors))


if __name__ == "__main__":
    unittest.main()
