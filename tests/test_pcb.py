import json
import unittest
from pathlib import Path

from clab.db import DB
from clab.document import Document
from clab.pcb import PcbLayout

ROOT = Path(__file__).resolve().parent.parent


class PcbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DB(ROOT / "data" / "components")

    def _doc(self, eid):
        raw = json.loads((ROOT / "data" / "exercises" / f"{eid}.json").read_text(encoding="utf-8"))
        return Document(raw, self.db)

    def test_exp03(self):
        pcb = PcbLayout(self._doc("exp03"))
        self.assertEqual(pcb.parts["R1"]["fp"].id, "R_axial")
        self.assertEqual(pcb.parts["D1"]["fp"].id, "LED_5mm")
        self.assertEqual(pcb.parts["V1"]["fp"].id, "TERM_2")
        w, h = pcb.board
        self.assertGreater(w, 20)
        self.assertGreater(h, 8)
        svg = pcb.to_svg()
        self.assertIn("<svg", svg)
        self.assertIn("R1", svg)
        self.assertIn("D1", svg)
        self.assertIn("<polyline", svg)
        self.assertIn("<circle", svg)
        self.assertEqual(pcb.violations, [])
        self.assertEqual(pcb.warnings, [])

    def test_all_exercises_have_footprints(self):
        for path in sorted((ROOT / "data" / "exercises").glob("*.json")):
            with self.subTest(exercise=path.stem):
                pcb = PcbLayout(self._doc(path.stem))
                self.assertEqual(pcb.violations, [])


if __name__ == "__main__":
    unittest.main()
