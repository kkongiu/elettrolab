import unittest
from types import SimpleNamespace

from clab.gui_simulation import expectations_from_result
from clab.schematic import move_bend


class GuiFeatureTests(unittest.TestCase):
    def test_expectations_are_captured_from_current_results(self):
        doc = SimpleNamespace(ground="gnd")
        result = SimpleNamespace(
            nodes={"gnd": 0.0, "input": 9.0, "out": 1.95},
            currents={"V1": -0.015, "R1": 0.015, "D1": 0.015, "R2": 0.0},
            violations=[],
        )
        expected = expectations_from_result(doc, result)
        self.assertNotIn("V(gnd)", expected)
        self.assertEqual(expected["V(out)"], {"approx": 1.95, "tol": 0.05})
        self.assertEqual(expected["I(D1)"]["approx"], 0.015)
        self.assertNotIn("I(R2)", expected)
        self.assertEqual(expected["violations"], [])

    def test_move_bend_keeps_endpoints_and_orthogonal_segments(self):
        moved = move_bend([(0, 0), (10, 0), (10, 10)], 1, 20, 30)
        self.assertEqual(moved[0], (0, 0))
        self.assertEqual(moved[-1], (10, 10))
        self.assertIn((20.0, 30.0), moved)
        for (x1, y1), (x2, y2) in zip(moved, moved[1:]):
            self.assertTrue(x1 == x2 or y1 == y2)


if __name__ == "__main__":
    unittest.main()
