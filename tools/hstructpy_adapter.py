#!/usr/bin/env python3
"""Run the repository's hstructpy without modifying its source tree.

This thin launcher keeps the suite portable while preserving hstructpy as an
independently versioned tool. Set HSTRUCTPY_ROOT when the source is elsewhere.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve()
    candidates = []
    if os.environ.get("HSTRUCTPY_ROOT"):
        candidates.append(Path(os.environ["HSTRUCTPY_ROOT"]).expanduser())
    candidates += [
        here.parents[2] / "grandStrainComparison" / "hstructpy",
        here.parents[3] / "grandStrainComparison" / "hstructpy",
    ]
    root = next((p for p in candidates if (p / "src" / "hstructpy").is_dir()), None)
    if root is None:
        raise SystemExit("hstructpy source not found; set HSTRUCTPY_ROOT=/path/to/hstructpy")
    sys.path.insert(0, str(root / "src"))
    # hstructpy's __main__ owns argument parsing and GUI/CLI selection.
    sys.argv[0] = "hstructpy"
    runpy.run_module("hstructpy", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
