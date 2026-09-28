# Heterostructure analysis API

EpiRefine provides one command and one Python namespace for four connected tasks:

1. orient two crystals and quantify their intrinsic in-plane mismatch;
2. place those mismatch coordinates on an epitaxial-strain contour;
3. propose auditable adaptive samples and scaffold VASP relax/static runs; and
4. render static slices from VASP volumetric data.

The adaptive workflow and contour plotting are native EpiRefine code. Crystal
orientation and mismatch calculations are delegated to the independently maintained
`hstructpy` package. Volumetric slices are delegated to the existing
`plot_polyhedron_slice.py` implementation. The API records the backend version,
path, and/or hash so a result can be reproduced without silently forking either tool.

## Discover companion tools

```bash
epirefine tool-status
epirefine tool-status --out provenance/tool_status.json
```

In the original research checkout, sibling tools are discovered automatically. In a
standalone checkout, point EpiRefine at them explicitly:

```bash
export HSTRUCTPY_ROOT=/path/to/hstructpy
export POLYHEDRON_SLICE_ROOT=/path/to/polyhedron_slice_tool
```

`HSTRUCTPY_ROOT` must contain `src/hstructpy`. The slice variable may name either
the tool directory or `plot_polyhedron_slice.py` itself. Missing optional tools raise
`ToolUnavailableError` in Python and produce exit status 2 in the CLI.

## Interface mismatch to contour marker

The mismatch convention is `100 * (substrate - film) / film`; positive values mean
the film must be put in tension to conform to the substrate.

```bash
epirefine interface-match substrate.cif film.vasp \
  --substrate-plane '(0001)' \
  --film-plane '(100)' \
  --out reports/al2o3_ruo2.json \
  --marker-out data/al2o3_marker.csv \
  --marker-plane 100 \
  --marker-label 'Al2O3(0001)'

epirefine plot \
  --input data/processed/static_history.csv \
  --markers data/al2o3_marker.csv \
  --out plots/with_interfaces
```

Use repeat flags for explicitly chosen domain matching, and swap flags when the
generated surface axes need to be compared in the opposite order:

```bash
epirefine interface-match substrate.vasp film.vasp \
  --substrate-repeats 2 1 --film-repeats 3 1 \
  --film-swap-axes --out reports/match.json
```

For hstructpy operations not promoted into the stable typed API—domain search,
structure building, batch comparison, or the GUI—use the transparent passthrough:

```bash
epirefine hstruct -- domain-search substrate.cif film.vasp --max-strain 10 --json
epirefine hstruct -- build substrate.cif film.vasp interface.vasp
```

The `--` separates EpiRefine arguments from hstructpy arguments.

## Python API

```python
from pathlib import Path
from epirefine import (
    AdaptiveProposalRequest,
    InterfaceMatchRequest,
    analyze_interface,
    marker_from_match,
    plot_contours,
    propose_iteration,
)

report = analyze_interface(InterfaceMatchRequest(
    substrate=Path("cells/Al2O3.cif"),
    film=Path("cells/RuO2.vasp"),
    substrate_plane="(0001)",
    film_plane="(100)",
))
marker = marker_from_match(report, plane="100", label="Al2O3(0001)")

decision = propose_iteration(AdaptiveProposalRequest(
    static_history=Path("data/processed/static_history.csv"),
    output_csv=Path("iterations/iter02/proposed_points.csv"),
    settings={"budget": 50, "iteration": "iter02", "planes": ["001", "100"]},
))

metadata = plot_contours(
    Path("data/processed/static_history.csv"),
    Path("plots/iter02"),
    markers_csv=Path("data/markers.csv"),
)
```

The proposal CSV is normally fed to `epirefine scaffold-relax`. If ionic relaxation
is unavailable, feed it to `epirefine scaffold-direct-static` instead and maintain a
separate fixed-geometry history. Previous outputs enter the next iteration through the
accumulated static history: collect the HPC results, ingest them with their static
manifest, and use the resulting CSV as the next `propose --input`. Geometry paths in
that history let the scaffolder choose the nearest accepted same-plane geometry.

The ingested `geometry_protocol` field distinguishes `relaxed_static` from
`direct_static`. Do not merge those protocols into one interpolated surface: the
former samples target-strain relaxed structures, while the latter samples an affine
fixed-geometry construction.

## Volumetric slice

```bash
epirefine volume-slice \
  --volume SPIN.vasp --dataset 0 \
  --center Ru2 --plane-atoms Ru2 O2 O5 \
  --output plots/ru2_slice.png \
  --report provenance/ru2_slice.json
```

Add `--dry-run` to resolve the backend and print the complete command without loading
the volume or creating a figure. The report records the backend script SHA-256 and,
after a real render, hashes of the PNG, XYZ, and text metadata outputs.

## VASPKIT extraction hook

VASPKIT is not a Python dependency and is never downloaded by EpiRefine. Acquire it
independently, complete its own configuration, and register the executable path on
each machine that will use it:

```bash
epirefine tool-config vaspkit --path /absolute/path/to/vaspkit
epirefine tool-status
```

The default registry is `~/.config/epirefine/tools.json`. Use `--tool-registry` for
a project/cluster-specific file, `EPIREFINE_TOOL_REGISTRY` to change the default, or
`VASPKIT_BIN` as a temporary executable override.

Bulk extraction walks all CHGCAR-containing directories beneath a run root. It uses
VASPKIT's noninteractive CLI tasks 311 (`CHARGE.vasp`), 312 (`SPIN.vasp`), and 313
(`SPIN_UP.vasp` and `SPIN_DW.vasp`):

```bash
epirefine extract-volumetric --root iterations/iter01/static \
  --products charge spin --dry-run
epirefine extract-volumetric --root iterations/iter01/static \
  --products charge spin --timeout 900
```

The same operation can be enabled inside the HPC collection step:

```bash
epirefine collect --root iterations/iter01/static \
  --archive /scratch/$USER/iter01_static.tar.gz \
  --vaspkit-extract charge spin --vaspkit-timeout 900
```

Dry-run collection does not invoke VASPKIT. A real extraction writes
`.epirefine-vaspkit.json`, records the executable SHA-256, task outcomes, output hashes,
and failures, and never packages the executable itself. Existing derived files are
skipped by default. Raw CHGCAR and licensed POTCAR remain excluded from the compact
archive; the generated viewer files are included. The static calculation must have
written CHGCAR (normally `LCHARG = .TRUE.`).

The task mapping and batch input mode follow the official
[VASPKIT density tutorial](https://vaspkit.com/tutorials.html) and
[feature list](https://vaspkit.com/features.html). Follow VASPKIT's own
[installation and usage terms](https://vaspkit.com/installation.html), and acknowledge
it when its results are used in publication.

## Dependency boundaries

- Basic HPC scaffolding, hydration, validation, submission, audit, and collection use
  only Python's standard library.
- Adaptive proposals and plots require the `local` dependencies.
- Typed interface matching requires ASE and NumPy plus an accessible hstructpy tree.
- The full local analysis environment is available with `pip install -e '.[analysis]'`.
- POTCAR files are never packaged, archived, or inferred. They are supplied at the
  licensed site with `epirefine hydrate` and tracked by checksum in each manifest.

The geometric mismatch API does not predict interface stability, registry,
termination, reconstruction, or interface energy. Those remain explicit modeling
choices and should not be mixed within one continuous strain response surface.
