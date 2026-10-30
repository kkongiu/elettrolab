import json
import tempfile
import unittest
from pathlib import Path

from clab.circuit import CircuitError, from_dict
from clab.db import DB
from clab.document import Document
from clab.layouts import LAYOUTS
from clab.solver import check, simulate

ROOT = Path(__file__).resolve().parent.parent
DB_ = DB(ROOT / "data" / "components")


def new_doc():
    return Document({"id": "test", "title": "test", "analysis": "dc",
                     "parts": {}, "nets": {}}, DB_,
                    layout={"parts": {}, "gnd_y": 330})


class DocumentTests(unittest.TestCase):
    def test_build_and_simulate(self):
        doc = new_doc()
        v = doc.add_part("battery_9v", 100, 210, 90)
        r = doc.add_part("resistor", 320, 100, 0)
        doc.set_param(r, "r", "470")
        d = doc.add_part("led_red", 560, 210, 90)
        g = doc.add_part("ground", 560, 320, 0)
        doc.connect(v, "+", r, "1")
        doc.connect(r, "2", d, "A")
        doc.connect(d, "K", g, "1")
        doc.connect(v, "-", g, "1")
        self.assertEqual(doc.errors(), [])
        res = simulate(doc.to_circuit())
        self.assertAlmostEqual(res.currents[d], 0.015, places=4)
        self.assertEqual(doc.ground, "gnd")
        self.assertEqual(len(doc.nets["gnd"]), 3)

    def test_merge_and_disconnect(self):
        doc = new_doc()
        r1 = doc.add_part("resistor", 100, 100)
        r2 = doc.add_part("resistor", 300, 100)
        r3 = doc.add_part("resistor", 500, 100)
        doc.connect(r1, "1", r2, "1")
        doc.connect(r2, "2", r3, "1")
        self.assertEqual(len(doc.nets), 2)
        doc.connect(r1, "2", r2, "2")
        self.assertEqual(doc.net_of(r1, "2"), doc.net_of(r2, "2"))
        doc.disconnect(r1, "2")
        self.assertIsNone(doc.net_of(r1, "2"))

    def test_ground_symbol(self):
        doc = new_doc()
        g = doc.add_part("ground", 400, 300)
        r = doc.add_part("resistor", 200, 200)
        doc.connect(r, "1", g, "1")
        self.assertEqual(doc.net_of(r, "1"), "gnd")

    def test_parameter_validation(self):
        doc = new_doc()
        r = doc.add_part("resistor")
        doc.set_param(r, "pmax", 10)
        sw = doc.add_part("switch_spst")
        doc.set_param(sw, "t_close", 0.02)
        doc.set_param(sw, "t_open", 0.04)
        self.assertFalse([p for p in doc.problems() if p["code"] == "unknown_parameter"])

        doc.set_param(r, "rr", "470")
        errors = [p for p in doc.problems() if p["code"] == "unknown_parameter"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["part"], r)
        self.assertEqual(errors[0]["parameter"], "rr")

    def test_numeric_values_and_ranges(self):
        doc = new_doc()
        r = doc.add_part("resistor")
        doc.set_param(r, "r", "not-a-value")
        sw = doc.add_part("switch_spst")
        doc.set_param(sw, "t_close", "later")
        pot = doc.add_part("potentiometer")
        doc.set_param(pot, "pos", 1.1)
        doc.set_param(sw, "closed", "false")

        errors = [p for p in doc.problems()
                  if p.get("parameter") in {"r", "t_close", "pos", "closed"}]
        self.assertEqual({(p["code"], p.get("parameter")) for p in errors}, {
            ("bad_value", "r"), ("bad_value", "t_close"),
            ("out_of_range", "pos"), ("bad_value", "closed"),
        })

    def test_timing_values_are_positive_and_bounded(self):
        doc = new_doc()
        doc.meta.update({"analysis": "transient", "dt": 0, "tstop": 100})
        errors = [p for p in doc.problems() if p["severity"] == "error"]
        self.assertTrue(any(p["code"] == "out_of_range" and "dt" in p["message"]
                            for p in errors))
        doc.meta["dt"] = 0.001
        doc.meta["tstop"] = 301
        errors = [p for p in doc.problems() if p["severity"] == "error"]
        self.assertTrue(any(p["code"] == "too_long" for p in errors))

    def test_circuit_rejects_invalid_parameter_values(self):
        raw = {
            "parts": {
                "V1": {"type": "battery_9v"},
                "R1": {"type": "resistor", "r": 0},
            },
            "nets": {
                "p": ["V1.+", "R1.1"],
                "gnd": ["V1.-", "R1.2"],
            },
        }
        with self.assertRaisesRegex(CircuitError, "R1.r: r: deve essere > 0"):
            from_dict(raw, DB_)

    def test_roundtrip(self):
        doc = new_doc()
        v = doc.add_part("battery_9v", 100, 210, 90)
        r = doc.add_part("resistor", 320, 100, 0)
        doc.set_param(r, "r", "470")
        d = doc.add_part("led_red", 560, 210, 90)
        g = doc.add_part("ground", 560, 320, 0)
        doc.connect(v, "+", r, "1")
        doc.connect(r, "2", d, "A")
        doc.connect(d, "K", g, "1")
        doc.connect(v, "-", g, "1")
        doc.move(r, 333, 111)
        data = json.loads(doc.to_json())
        layout = json.loads(doc.to_json(layout=True))
        doc2 = Document.from_dict(data, DB_, layout=layout)
        self.assertEqual(doc2.parts, doc.parts)
        self.assertEqual(doc2.nets, doc.nets)
        self.assertEqual(doc2.position(r), [333, 111, 0])
        self.assertAlmostEqual(simulate(doc2.to_circuit()).currents[d], 0.015, places=4)

    def test_delete_cleans(self):
        doc = new_doc()
        v = doc.add_part("battery_9v", 100, 210)
        r = doc.add_part("resistor", 300, 100)
        doc.connect(v, "+", r, "1")
        doc.delete_part(v)
        self.assertNotIn(v, doc.parts)
        self.assertNotIn(f"{v}.+", [ref for refs in doc.nets.values() for ref in refs])

    def test_optional_relay_contact(self):
        raw = json.loads((ROOT / "data" / "exercises" / "exp08b.json").read_text())
        doc = Document(raw, DB_, layout=LAYOUTS["exp08b"])
        self.assertEqual(doc.errors(), [])
        circ = doc.to_circuit()
        res = simulate(circ)
        check(circ, res)
        self.assertTrue(res.ok)
        self.assertGreater(max(res.waves["I(D1)"]), 0.008)
        self.assertGreater(max(res.waves["I(D2)"]), 0.008)

    def test_sidecar_files(self):
        doc = new_doc()
        doc.add_part("ground", 100, 300)
        with tempfile.TemporaryDirectory() as tmp:
            cpath = Path(tmp) / "p.json"
            lpath = Path(tmp) / "p.layout.json"
            doc.save(cpath, lpath)
            self.assertTrue(cpath.exists())
            self.assertTrue(lpath.exists())
            loaded = Document.from_file(cpath, lpath, DB_)
            self.assertEqual(loaded.nets, doc.nets)


if __name__ == "__main__":
    unittest.main()
