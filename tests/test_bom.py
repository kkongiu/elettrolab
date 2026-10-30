import json
import unittest
from pathlib import Path

from clab.bom import build_bom, money, to_csv, to_html
from clab.db import DB
from clab.document import Document


ROOT = Path(__file__).resolve().parents[1]


class BillOfMaterialsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = DB(ROOT / "data" / "components")

    def _project(self):
        data = json.loads((ROOT / "data/projects/powerbank_usb_1s.json").read_text())
        data["title"] = "Power bank <test>"
        data["parts"]["RCC1"]["unit_cost"] = 0.12
        data["parts"]["RCC2"]["unit_cost"] = 0.12
        data["parts"]["RCC1"]["currency"] = "EUR"
        data["parts"]["RCC2"]["currency"] = "EUR"
        data["parts"]["RISET"]["unit_cost"] = 0.2
        return Document(data, self.db)

    def test_groups_parts_and_totals_only_known_prices(self):
        rows, totals, unpriced = build_bom(self._project())
        cc = next(row for row in rows if row["references"] == "RCC1, RCC2")
        self.assertEqual(cc["quantity"], 2)
        self.assertEqual(cc["value"], "5.1 k\u03a9")
        self.assertEqual(cc["unit_cost"], 0.12)
        self.assertAlmostEqual(cc["subtotal"], 0.24)
        self.assertAlmostEqual(totals["EUR"], 0.44)
        self.assertGreater(unpriced, 0)
        self.assertFalse(any("G1" in row["references"] for row in rows))
        self.assertFalse(any("VUSB" in row["references"] or
                             "RLOAD" in row["references"] for row in rows))

    def test_html_and_csv_exports_are_printable_and_safe(self):
        doc = self._project()
        rows, totals, unpriced = build_bom(doc)
        page = to_html(doc, rows, totals, unpriced)
        self.assertIn("window.print()", page)
        self.assertIn("Power bank &lt;test&gt;", page)
        self.assertIn("componenti senza prezzo inserito", page.lower())
        csv_text = to_csv(rows)
        self.assertIn("Quantita;Componente;Valore", csv_text)
        self.assertIn("RCC1, RCC2", csv_text)

    def test_euro_format(self):
        self.assertEqual(money(1234.5), "1.234,50 EUR")
        self.assertEqual(money(None), "—")


if __name__ == "__main__":
    unittest.main()
