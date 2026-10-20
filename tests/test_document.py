import json
import tempfile
import unittest
from pathlib import Path

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
