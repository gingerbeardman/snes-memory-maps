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

    def test_csv_is_opt_in(self):
        # default: SVG only, no CSV
        prefix, _ = self.run_tool("rommap.py")
        self.assertTrue(prefix.with_suffix(".svg").exists())
        self.assertFalse(prefix.with_suffix(".csv").exists())

    def test_rom_outputs_csv_and_valid_svg(self):
        prefix, result = self.run_tool("rommap.py", "--csv")
        self.assertIn("93.8% allocated", result.stdout)

        with prefix.with_suffix(".csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(["main", "assets"], [row["symbol"] for row in rows])

        root = ET.parse(prefix.with_suffix(".svg")).getroot()
        self.assertEqual("SNES ROM MAP", root.findtext("svg:title", namespaces=SVG))
        critical = root.findall('.//svg:tspan[@class="capacity-critical"]', SVG)
        self.assertEqual([], critical)

    def test_ram_outputs_classified_csv_and_valid_svg(self):
        prefix, result = self.run_tool("rammap.py", "--csv", include_linker=False)
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
            "rommap.py", "--csv", include_linker=False, map_name="vlink.map"
        )
        with rom_prefix.with_suffix(".csv").open(newline="") as stream:
            rom_rows = list(csv.DictReader(stream))
        self.assertEqual(["main", "assets"], [row["symbol"] for row in rom_rows])

        ram_prefix, _ = self.run_tool(
            "rammap.py", "--csv", include_linker=False, map_name="vlink.map"
        )
        with ram_prefix.with_suffix(".csv").open(newline="") as stream:
            ram_rows = list(csv.DictReader(stream))
        self.assertEqual(["state", "buffer"], [row["symbol"] for row in ram_rows])
        self.assertEqual({"allocated"}, {row["allocation"] for row in ram_rows})


    def test_ca65_segment_map_is_exact(self):
        rom_prefix, result = self.run_tool(
            "rommap.py", "--csv",
            "--linker-script", str(FIXTURES / "ca65.cfg"),
            include_linker=False, map_name="ca65.map",
        )
        self.assertIn("93.8% allocated", result.stdout)
        with rom_prefix.with_suffix(".csv").open(newline="") as stream:
            rom_rows = list(csv.DictReader(stream))
        self.assertEqual(["main", "assets"], [row["symbol"] for row in rom_rows])
        # segment sizes are read straight from the ld65 "Segment list", not inferred
        self.assertEqual(["4096", "26624"], [row["size"] for row in rom_rows])

        ram_prefix, _ = self.run_tool(
            "rammap.py", "--csv", include_linker=False, map_name="ca65.map"
        )
        with ram_prefix.with_suffix(".csv").open(newline="") as stream:
            allocations = {row["symbol"]: row["allocation"]
                           for row in csv.DictReader(stream)}
        self.assertEqual("data", allocations["DATA"])
        self.assertEqual("bss", allocations["BSS"])

    def run_expecting_error(self, script, *args):
        """Run a script in an empty working directory and require a clean
        non-zero exit (argparse error, not a traceback)."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        command = [sys.executable, str(ROOT / script), *args,
                   "-o", str(Path(temporary.name) / "out")]
        result = subprocess.run(command, cwd=temporary.name,
                                text=True, capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def test_ca65_map_works_without_a_linker_config(self):
        # Regression: a ca65 map on its own must not crash on a missing game.ld;
        # it falls back to LoROM physical banks (sizes stay exact).
        prefix, _ = self.run_tool(
            "rommap.py", "--csv", include_linker=False, map_name="ca65.map"
        )
        with prefix.with_suffix(".csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(["main", "assets"], [row["symbol"] for row in rows])
        self.assertTrue(all(row["region"].startswith("bank_") for row in rows))

    def test_missing_map_file_fails_cleanly(self):
        result = self.run_expecting_error("rommap.py", "does-not-exist.map")
        self.assertIn("cannot read map/symbol file", result.stderr)

    def test_lld_rom_without_linker_script_fails_cleanly(self):
        result = self.run_expecting_error("rommap.py", str(FIXTURES / "game.map"))
        self.assertIn("--linker-script", result.stderr)

    def test_wla_and_asar_symbol_files_infer_sizes(self):
        for map_name, label in (("wla.sym", "wla-dx"), ("asar.sym", "asar")):
            prefix, _ = self.run_tool(
                "rommap.py", "--csv", include_linker=False, map_name=map_name
            )
            with prefix.with_suffix(".csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(["main", "assets"], [row["symbol"] for row in rows])
            # a label's size is the exact gap to the next label...
            self.assertEqual("4096", rows[0]["size"])
            # ...and the final label in a bank is extended to the bank end.
            self.assertEqual("28672", rows[1]["size"])
            svg = prefix.with_suffix(".svg").read_text()
            self.assertIn(label, svg)
            self.assertIn("approx sizes", svg)


if __name__ == "__main__":
    unittest.main()
