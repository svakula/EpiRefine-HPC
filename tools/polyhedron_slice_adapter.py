#!/usr/bin/env python3
"""Launch the existing polyhedron slice viewer from the suite root.

The viewer remains unmodified in ``spindensityexploration``. This adapter is
deliberately a locator, so data and behavior cannot silently diverge.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve()
    target = here.parents[2] / "spindensityexploration" / "BondStrainPY" / "5-21-bondstrainer" / "polyhedron_slice_tool" / "interactive_polyhedron_slice.py"
    if not target.is_file():
        raise SystemExit(f"viewer not found: {target}")
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
