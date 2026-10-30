import json
import math
import unittest
from pathlib import Path

from clab.db import DB
from clab.document import Document
from clab.pcb import PcbLayout
from clab.schematic import Schematic
from clab.solver import check, simulate


ROOT = Path(__file__).resolve().parents[1]


class FakeCanvas:
    def __init__(self):
        self.calls = []

    def create_polygon(self, *args, **kwargs):
        self.calls.append(("polygon", args, kwargs))

    def create_line(self, *args, **kwargs):
        self.calls.append(("line", args, kwargs))

    def create_text(self, *args, **kwargs):
        self.calls.append(("text", args, kwargs))


class PowerbankComponentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = DB(ROOT / "data" / "components")
        cls.doc = Document.from_file(
            ROOT / "data" / "projects" / "powerbank_usb_1s.json",
            ROOT / "data" / "projects" / "powerbank_usb_1s.layout.json",
            db,
        )

    def test_project_has_all_pins_connected_and_simulates_nominal_dc(self):
        self.assertEqual(self.doc.errors(), [])
        self.assertEqual(self.doc.meta["analysis"], "dc")
        circ = self.doc.to_circuit()
        self.assertEqual(circ.analysis, "dc")
        result = simulate(circ)
        check(circ, result)
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.nodes["usb_in_5v"], 5.0, places=3)
        self.assertAlmostEqual(result.nodes["battery_plus"], 3.68, places=1)
        self.assertGreater(result.nodes["usb_out_5v"], 4.75)
        self.assertLess(result.nodes["usb_out_5v"], 5.1)
        self.assertAlmostEqual(result.currents["RLOAD"], 5.0 / 5.0, delta=0.1)
        self.assertEqual(result.violations, [])

    def test_usb_current_limit_uses_ilim_resistor(self):
        data = self.doc.to_dict()
        data["parts"]["RLOAD"]["r"] = "2"
        doc = Document(data, self.doc.db)
        circ = doc.to_circuit()
        result = simulate(circ)
        check(circ, result)
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.currents["U3"], result.currents["RLOAD"], places=4)
        self.assertGreater(result.currents["U3"], 1.0)
        self.assertLess(result.currents["U3"], 1.1)

    def test_symbols_have_complete_side_maps(self):
        for typ in ("bq24074", "tps61023", "tps2553", "protection_liion_1s",
                    "usb_esd_array", "usb_vbus_tvs", "usb_c_sink_5v", "usb_a_source"):
            spec = self.doc.db.types[typ]
            mapped = [pin for pins in spec.pin_sides.values() for pin in pins]
            self.assertEqual(sorted(mapped), sorted(spec.pins))
            self.assertEqual(len(mapped), len(set(mapped)))

    def test_block_pin_positions_are_distinct(self):
        schematic = Schematic.__new__(Schematic)
        schematic.doc = self.doc
        schematic.layout = self.doc.layout
        for pid in ("U1", "U2", "U3", "J1", "J2", "PCM1"):
            points = [schematic._pin(pid, pin) for pin in self.doc.pins(pid)]
            self.assertEqual(len(points), len(set(points)))
            for x, y in points:
                self.assertTrue(math.isfinite(x))
                self.assertTrue(math.isfinite(y))

    def test_project_schematic_routes_all_declared_nets(self):
        schematic = Schematic(object(), self.doc)
        routed_nets = {path.net for path in schematic.paths}
        self.assertEqual(routed_nets, set(self.doc.nets))

    def test_ic_and_connector_symbols_draw_as_blocks(self):
        canvas = FakeCanvas()
        schematic = Schematic(canvas, self.doc)
        schematic._draw_part("U1", None)
        schematic._draw_part("J1", None)
        self.assertEqual(sum(call[0] == "polygon" for call in canvas.calls), 2)
        self.assertGreater(sum(call[0] == "line" for call in canvas.calls), 10)

    def test_battery_component_remains_a_fixed_voltage_source(self):
        battery = self.doc.part("BAT1")
        self.assertEqual(battery.type, "battery_liion_1s")
        self.assertEqual(battery.kind, "V")
        self.assertAlmostEqual(battery.num("v"), 3.7)
        self.assertIn("non simula", battery.spec.learn.lower())

    def test_project_file_declares_its_approximate_model_scope(self):
        raw = json.loads((ROOT / "data" / "projects" / "powerbank_usb_1s.json").read_text())
        self.assertEqual(raw["analysis"], "dc")
        self.assertIn("semplificati", raw["notes"])
        self.assertTrue(raw["parts"]["VUSB"]["simulation_only"])
        self.assertTrue(raw["parts"]["RLOAD"]["simulation_only"])

    def test_powerbank_pcb_uses_smd_footprints_and_physical_pad_maps(self):
        pcb = PcbLayout(self.doc)
        self.assertEqual(pcb.violations, [])
        self.assertNotIn("VUSB", pcb.parts)
        self.assertNotIn("RLOAD", pcb.parts)
        expected = {
            "U1": "BQ24074_VQFN16", "U2": "TPS61023_SOT563",
            "U3": "TPS2553_SOT23_6", "RCC1": "R_0603",
            "CIN": "C_0805", "L1": "L_3x3", "J1": "USB_C_GENERIC",
        }
        for pid, fid in expected.items():
            with self.subTest(part=pid):
                self.assertEqual(pcb.parts[pid]["fp"].id, fid)
        bq = pcb.parts["U1"]
        self.assertEqual(bq["fp"].net_pin("17"), "GND")
        self.assertTrue(all(bq["fp"].pad_drill(pin) == 0 for pin in bq["pads"]))
        svg = pcb.to_svg()
        self.assertIn("<rect", svg)
        self.assertIn("USB_C_GENERIC", {pcb.parts["J1"]["fp"].id})
