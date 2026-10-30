import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from xml.etree import ElementTree
from pathlib import Path

try:
    from clab_mcp import service
    HAS_SERVICE = True
except Exception:
    HAS_SERVICE = False

ROOT = Path(__file__).resolve().parent.parent


def load(eid):
    return json.loads((ROOT / "data" / "exercises" / f"{eid}.json").read_text())


@unittest.skipUnless(HAS_SERVICE, "clab_mcp non disponibile")
class MCPServiceTests(unittest.TestCase):
    def test_catalog_and_component(self):
        cat = service.catalog()
        ids = {c["id"] for c in cat["components"]}
        self.assertIn("resistor", ids)
        self.assertIn("transistor_npn", ids)
        one = service.component("led_red")
        self.assertTrue(one["ok"])
        self.assertEqual(one["component"]["kind"], "LED")
        self.assertFalse(service.component("nope")["ok"])

    def test_exercises_and_get(self):
        ex = service.list_exercises()
        ids = {e["id"] for e in ex["exercises"]}
        self.assertIn("exp03", ids)
        got = service.get_circuit("exp03")
        self.assertTrue(got["ok"])
        self.assertEqual(got["circuit"]["id"], "exp03")
        self.assertIsNotNone(got["layout"])

    def test_validate_good_and_bad(self):
        good = load("exp03")
        self.assertTrue(service.validate(good)["ok"])
        bad = json.loads(json.dumps(good))
        del bad["nets"]["gnd"]
        result = service.validate(bad)
        self.assertFalse(result["ok"])
        self.assertTrue(any(e["code"] == "no_ground" for e in result["errors"]))

    def test_simulate_dc_and_transient(self):
        dc = service.simulate(load("exp03"))
        self.assertTrue(dc["ok"])
        self.assertAlmostEqual(dc["nodes"]["m"], 1.95, places=3)
        self.assertAlmostEqual(dc["currents"]["D1"], 0.015, places=4)
        tr = service.simulate(load("exp09"), include_waveforms=True, max_points=30)
        self.assertTrue(tr["ok"])
        self.assertLessEqual(len(tr["time"]), 30)
        self.assertIn("V(m)", tr["waves"])
        self.assertAlmostEqual(tr["summary"]["V(m)"]["max"], 8.55, delta=0.1)

    def test_render_schematic_svg(self):
        result = service.render_schematic(cid="exp03")
        self.assertTrue(result["ok"])
        self.assertEqual(result["format"], "image/svg+xml")
        self.assertIn("<svg", result["svg"])
        self.assertIn("V1", result["svg"])
        self.assertIn("D1", result["svg"])
        self.assertEqual(ElementTree.fromstring(result["svg"]).tag,
                         "{http://www.w3.org/2000/svg}svg")

    def test_ac_sweep_service(self):
        circuit = {
            "id": "rc_low_pass",
            "parts": {
                "V1": {"type": "battery_9v"},
                "R1": {"type": "resistor", "r": 1000},
                "C1": {"type": "capacitor", "c": 1e-6},
            },
            "nets": {"in": ["V1.+", "R1.1"],
                     "out": ["R1.2", "C1.+"],
                     "gnd": ["V1.-", "C1.-"]},
        }
        result = service.ac_sweep(circuit, "V1", "out", 10, 1000, 51)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["frequency"]), 51)
        self.assertLess(result["magnitude_db"][-1], result["magnitude_db"][0])

    def test_check_and_sweep(self):
        self.assertTrue(service.check(cid="exp03")["ok"])
        rows = service.sweep(load("exp04"), "POT1", "pos", [0, 0.5, 1], "I(D1)")
        self.assertTrue(rows["ok"])
        self.assertAlmostEqual(rows["rows"][0]["final"], 0.015, places=3)
        self.assertAlmostEqual(rows["rows"][-1]["final"], 0.0, places=6)

    def test_write_disabled(self):
        old = os.environ.get("CLAB_MCP_ALLOW_WRITE")
        os.environ["CLAB_MCP_ALLOW_WRITE"] = "0"
        try:
            res = service.add_component({"id": "x", "kind": "R", "name": "x",
                                         "pins": ["1", "2"]})
            self.assertFalse(res["ok"])
            self.assertEqual(res["errors"][0]["code"], "write_disabled")
        finally:
            if old is None:
                os.environ.pop("CLAB_MCP_ALLOW_WRITE", None)
            else:
                os.environ["CLAB_MCP_ALLOW_WRITE"] = old

    def test_write_enabled_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copytree(ROOT / "data" / "components", tmp / "components")
            (tmp / "projects").mkdir()
            old_data = os.environ.get("CLAB_DATA_DIR")
            old_write = os.environ.get("CLAB_MCP_ALLOW_WRITE")
            os.environ["CLAB_DATA_DIR"] = str(tmp)
            os.environ["CLAB_MCP_ALLOW_WRITE"] = "1"
            try:
                res = service.add_component({
                    "id": "test_component", "kind": "R", "name": "Test",
                    "pins": ["1", "2"], "params": {"r": "1k"},
                })
                self.assertTrue(res["ok"])
                self.assertTrue((tmp / "components" / "test_component.json").exists())
                circuit = load("exp03")
                circuit["id"] = "test_exercise"
                res = service.add_exercise(circuit)
                self.assertTrue(res["ok"])
                self.assertTrue((tmp / "projects" / "test_exercise.json").exists())
                ids = {e["id"] for e in service.list_exercises()["exercises"]}
                self.assertIn("test_exercise", ids)
            finally:
                if old_data is None:
                    os.environ.pop("CLAB_DATA_DIR", None)
                else:
                    os.environ["CLAB_DATA_DIR"] = old_data
                if old_write is None:
                    os.environ.pop("CLAB_MCP_ALLOW_WRITE", None)
                else:
                    os.environ["CLAB_MCP_ALLOW_WRITE"] = old_write

    def test_end_to_end_loop(self):
        try:
            import anyio
            from mcp.client.stdio import StdioServerParameters, stdio_client
            from mcp import ClientSession
        except ImportError:
            self.skipTest("SDK MCP non installato")

        async def call(session, name, args):
            res = await session.call_tool(name, args)
            return json.loads(res.content[0].text)

        async def run():
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "clab_mcp"], cwd=str(ROOT),
                env={**os.environ, "CLAB_MCP_ALLOW_WRITE": "0"})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    got = await call(session, "get_circuit", {"id": "exp03"})
                    self.assertTrue(got["ok"])
                    circuit = got["circuit"]

                    broken = copy.deepcopy(circuit)
                    del broken["nets"]["gnd"]
                    invalid = await call(session, "validate_circuit", {"circuit": broken})
                    self.assertFalse(invalid["ok"])
                    self.assertIn("no_ground", {e["code"] for e in invalid["errors"]})

                    valid = await call(session, "validate_circuit", {"circuit": circuit})
                    self.assertTrue(valid["ok"])

                    sim = await call(session, "simulate_circuit", {"circuit": circuit})
                    self.assertTrue(sim["ok"])
                    self.assertAlmostEqual(sim["currents"]["D1"], 0.015, places=4)

                    chk = await call(session, "check_circuit", {"circuit": circuit})
                    self.assertTrue(chk["ok"])

                    wr = await call(session, "add_component", {
                        "definition": {"id": "x", "kind": "R", "name": "x",
                                       "pins": ["1", "2"]}})
                    self.assertFalse(wr["ok"])
                    self.assertEqual(wr["errors"][0]["code"], "write_disabled")

                    resource = await session.read_resource("clab://exercise/exp03")
                    self.assertIn("exp03", resource.contents[0].text)

                    prompt = await session.get_prompt(
                        "progetta_circuito", {"obiettivo": "accendere un LED"})
                    self.assertIn("LED", prompt.messages[0].content.text)

        anyio.run(run)

    def test_stdio_transport(self):
        try:
            import anyio
            from mcp.client.stdio import StdioServerParameters, stdio_client
            from mcp import ClientSession
        except ImportError:
            self.skipTest("SDK MCP non installato")

        async def run():
            params = StdioServerParameters(command=sys.executable,
                                           args=["-m", "clab_mcp"],
                                           cwd=str(ROOT))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}
                    self.assertIn("simulate_circuit", names)
                    self.assertIn("validate_circuit", names)
                    res = await session.call_tool("list_components", {})
                    self.assertFalse(getattr(res, "isError", False))

        anyio.run(run)


if __name__ == "__main__":
    unittest.main()
