#!/usr/bin/env python3
"""Generate an SNES ROM CSV/SVG map from an ld.lld or vlink linker map."""

import os
import runpy
import sys


generator = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snesmap.py")
os.environ["SNES_MEMORY_MAP_PROGRAM"] = "rommap.py"
os.environ["SNES_MEMORY_MAP_KIND"] = "rom"
sys.argv = [generator, "--map-kind", "rom", *sys.argv[1:]]
runpy.run_path(generator, run_name="__main__")
