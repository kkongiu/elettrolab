import copy
import json
import unittest
from pathlib import Path

from clab.breadboards import (LayoutError, derive_nets, generate, hole_xy, reroute,
                             rotate_part, shift_part, validate_layout, wire_at)
from clab.circuit import from_dict
from clab.db import DB
from clab.document import Document

ROOT = Path(__file__).resolve().parent.parent
DB_ = DB(ROOT / "data" / "components")


def load(eid):
    data = json.loads((ROOT / "data" / "exercises" / f"{eid}.json").read_text())
    return from_dict(data, DB_)


def load_doc(eid):
    data = json.loads((ROOT / "data" / "exercises" / f"{eid}.json").read_text())
    return Document(data, DB_)


class BreadboardTests(unittest.TestCase):
    def test_geometry(self):
        self.assertEqual(hole_xy("A5"), (196, 120))
        self.assertEqual(hole_xy("T+1"), (100, 62))
        with self.assertRaises(ValueError):
            hole_xy("Z1")

    def test_all_exercises_generate_valid_layouts(self):
        for path in sorted((ROOT / "data" / "exercises").glob("*.json")):
            eid = path.stem
            with self.subTest(exercise=eid):
                circ = load(eid)
                layout = generate(circ)
                errors = validate_layout(circ, layout)
                self.assertEqual(errors, [])
                for pid, part in circ.parts.items():
                    self.assertIn(pid, layout["parts"])
                    for pin in part.spec.pins:
                        self.assertIn(pin, layout["parts"][pid]["pins"])

    def test_derive_nets_matches_circuit(self):
        for path in sorted((ROOT / "data" / "exercises").glob("*.json")):
            eid = path.stem
            with self.subTest(exercise=eid):
                circ = load(eid)
                layout = generate(circ)
                derived = derive_nets(circ, layout)
                self.assertEqual({frozenset(v) for v in derived.values()},
                                 {frozenset(v) for v in circ.nets.values()})
                self.assertIn("gnd", derived)

    def test_manual_jumper_changes_nets(self):
        circ = load("exp03")
        layout = generate(circ)
        h1 = layout["parts"]["D1"]["pins"]["A"]
        h2 = layout["parts"]["V1"]["pins"]["-"]
        layout["wires"].append({"net": "fisico", "points": [h1, h2]})
        derived = derive_nets(circ, layout)
        self.assertIn("D1.A", derived["gnd"])
        self.assertIn("R1.2", derived["gnd"])
        self.assertNotIn("m", derived)
        self.assertIsNotNone(wire_at(layout, *hole_xy(h1)))

    def test_move_carries_wires(self):
        circ = load("exp03")
        layout = generate(circ)
        original = {frozenset(v) for v in derive_nets(circ, layout).values()}
        old_pin = layout["parts"]["D1"]["pins"]["A"]
        attached = [i for i, wire in enumerate(layout["wires"])
                    if old_pin in wire["points"]]
        self.assertTrue(attached)
        ok, msg = False, "nessuna direzione libera"
        for dcol, drow in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            candidate = copy.deepcopy(layout)
            ok, msg = shift_part(circ, candidate, "D1", dcol, drow)
            if ok:
                break
        self.assertTrue(ok, msg)
        new_pin = candidate["parts"]["D1"]["pins"]["A"]
        self.assertNotEqual(old_pin, new_pin)
        for i in attached:
            self.assertIn(new_pin, candidate["wires"][i]["points"])
            self.assertNotIn(old_pin, candidate["wires"][i]["points"])
        self.assertEqual({frozenset(v) for v in derive_nets(circ, candidate).values()},
                         original)
        self.assertEqual(validate_layout(circ, candidate), [])

    def test_manual_jumper_is_reversible(self):
        circ = load("exp03")
        layout = generate(circ)
        h1 = layout["parts"]["D1"]["pins"]["A"]
        h2 = layout["parts"]["V1"]["pins"]["-"]
        layout["wires"].append({"net": "fisico", "points": [h1, h2]})
        merged = derive_nets(circ, layout)
        self.assertIn("D1.A", merged["gnd"])
        self.assertNotIn("m", merged)
        layout["wires"].pop()
        restored = derive_nets(circ, layout)
        self.assertIn("m", restored)
        self.assertIn("D1.A", restored["m"])

    def test_generation_is_deterministic(self):
        circ = load("exp10")
        self.assertEqual(generate(circ), generate(circ))

    def test_missing_pin_is_detected(self):
        circ = load("exp03")
        layout = generate(circ)
        layout["parts"]["R1"]["pins"].pop("1")
        errors = validate_layout(circ, layout)
        self.assertTrue(any(e["code"] == "no_pin" for e in errors))

    def test_short_is_detected(self):
        circ = load("exp03")
        layout = generate(circ)
        layout["wires"].append({
            "net": "m",
            "points": [layout["parts"]["D1"]["pins"]["A"],
                       layout["parts"]["V1"]["pins"]["-"]],
        })
        errors = validate_layout(circ, layout)
        self.assertTrue(any(e["code"] == "short" for e in errors))

    def test_shift_rotate_and_reroute(self):
        doc = load_doc("exp03")
        layout = generate(doc)
        doc.board = layout
        ok, msg = False, "nessuna direzione libera"
        for dcol, drow in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1)):
            ok, msg = shift_part(doc, layout, "R1", dcol, drow)
            if ok:
                break
        self.assertTrue(ok, msg)
        reroute(doc, layout)
        self.assertEqual(validate_layout(doc, layout), [])
        ok, msg = rotate_part(doc, layout, "R1")
        self.assertTrue(ok, msg)
        reroute(doc, layout)
        self.assertEqual(validate_layout(doc, layout), [])

    def test_board_sidecar_roundtrip(self):
        import tempfile
        doc = load_doc("exp03")
        doc.board = generate(doc)
        with tempfile.TemporaryDirectory() as tmp:
            cpath = Path(tmp) / "p.json"
            lpath = Path(tmp) / "p.layout.json"
            bpath = Path(tmp) / "p.board.json"
            doc.save(cpath, lpath, bpath)
            self.assertTrue(bpath.exists())
            loaded = Document.from_file(cpath, lpath, DB_, board_path=bpath)
            self.assertEqual(json.loads(json.dumps(loaded.board)),
                             json.loads(json.dumps(doc.board)))

    def test_add_and_delete_parts_regenerate(self):
        doc = load_doc("exp03")
        doc.add_part("resistor", 500, 300)
        layout = generate(doc)
        self.assertEqual(validate_layout(doc, layout), [])
        doc.delete_part("R1")
        layout = generate(doc)
        self.assertNotIn("R1", layout["parts"])
        self.assertEqual(validate_layout(doc, layout), [])


if __name__ == "__main__":
    unittest.main()
