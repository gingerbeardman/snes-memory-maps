import csv
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SVG = {"svg": "http://www.w3.org/2000/svg"}


class CommandLineTests(unittest.TestCase):
    def run_tool(self, script, *options, include_linker=True, map_name="game.map"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        prefix = Path(temporary.name) / script.removesuffix(".py")
        command = [
            sys.executable,
            str(ROOT / script),
            str(FIXTURES / map_name),
            "-o",
            str(prefix),
        ]
        if include_linker:
            command.extend(["--linker-script", str(FIXTURES / "game.ld")])
        command.extend(options)
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        return prefix, result

    def test_rom_outputs_csv_and_valid_svg(self):
        prefix, result = self.run_tool("rommap.py")
        self.assertIn("93.8% allocated", result.stdout)

        with prefix.with_suffix(".csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(["main", "assets"], [row["symbol"] for row in rows])

        root = ET.parse(prefix.with_suffix(".svg")).getroot()
        self.assertEqual("SNES ROM MAP", root.findtext("svg:title", namespaces=SVG))
        critical = root.findall('.//svg:tspan[@class="capacity-critical"]', SVG)
        self.assertEqual([], critical)

    def test_ram_outputs_classified_csv_and_valid_svg(self):
        prefix, result = self.run_tool("rammap.py", include_linker=False)
        self.assertIn("356", result.stdout)

        with prefix.with_suffix(".csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        allocations = {row["symbol"]: row["allocation"] for row in rows}
        self.assertEqual("compiler", allocations["compiler direct-page registers"])
        self.assertEqual("stack", allocations["hardware stack (reserved)"])
        self.assertEqual("data", allocations["state"])
        self.assertEqual("bss", allocations["buffer"])
        self.assertEqual("noinit", allocations["scratch"])

        root = ET.parse(prefix.with_suffix(".svg")).getroot()
        self.assertEqual("SNES RAM MAP", root.findtext("svg:title", namespaces=SVG))

    def test_optional_visual_treatments(self):
        prefix, _ = self.run_tool(
            "rommap.py",
            "--checkerboard",
            "--colour-key",
            "--coloured-percentages",
        )
        svg = prefix.with_suffix(".svg").read_text()
        self.assertIn('fill="url(#free-pattern)"', svg)
        self.assertIn('class="capacity-critical"', svg)
        self.assertIn("checkerboard = free space", svg)

    def test_vlink_rom_and_ram_are_auto_detected(self):
        rom_prefix, _ = self.run_tool(
            "rommap.py", include_linker=False, map_name="vlink.map"
        )
        with rom_prefix.with_suffix(".csv").open(newline="") as stream:
            rom_rows = list(csv.DictReader(stream))
        self.assertEqual(["main", "assets"], [row["symbol"] for row in rom_rows])

        ram_prefix, _ = self.run_tool(
            "rammap.py", include_linker=False, map_name="vlink.map"
        )
        with ram_prefix.with_suffix(".csv").open(newline="") as stream:
            ram_rows = list(csv.DictReader(stream))
        self.assertEqual(["state", "buffer"], [row["symbol"] for row in ram_rows])
        self.assertEqual({"allocated"}, {row["allocation"] for row in ram_rows})


if __name__ == "__main__":
    unittest.main()
