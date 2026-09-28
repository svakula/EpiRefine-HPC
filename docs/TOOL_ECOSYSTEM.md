# EpiRefine-HPC companion-tool ecosystem

EpiRefine-HPC is the reproducible, resource-aware workflow for constructing
epitaxially strained cells, selecting/refining a small set of DFT points,
collecting OUTCARs on an HPC system, and plotting scalar fields. The companion
tools answer the structural questions that precede and follow that loop.

The optional `epirefine-tui` is a guided front end for the same APIs and CLI. It is
not a separate scientific implementation; see the [TUI guide](TUI.md).

## Inventory and inclusion decision

| Existing location | Capability | Suite status | Reason |
|---|---|---|---|
| `grandStrainComparison/hstructpy` | surface orientation, coincidence/domain matching, finite-strain reports, periodic heterostructure export | **include via adapter** | Directly defines substrate/film orientation and a defensible strain search. Keep source independent; do not fork it. |
| `StrainContour/ruo2_2d_static_magnetization_2026-09-16` | Delaunay-guided adaptive sampling, OUTCAR reduction, three-panel contours, next-iteration scaffolding | **scientific lineage; leave untouched** | EpiRefine independently consolidates the generalizable behavior and does not import the study-specific scripts. |
| `StrainContour/gen2DStruct*.py`, `contcarMV_v2.py` | oriented/strained VASP geometry generation and historical CONTCAR handling | **lineage/reference only** | EpiRefine contains its own tested, manifest-driven nearest-CONTCAR rescaler; the older scripts retain study provenance. |
| `spindensityexploration/BondStrainPY/bond_strainer_core.py` and bond-strain studies | Ru–O bond-mode strain and local-geometry diagnostics | **documented research extension** | Valuable for post-refinement interpretation, but has study-specific assumptions and no stable public API yet. |
| `spindensityexploration/BondStrainPY/5-21-bondstrainer/polyhedron_slice_tool` | interactive planar/polyhedron slices of local geometry or volumetric data | **include via adapter** | Useful for validating interface-local distortions and spin-density features without duplicating code. |
| external VASPKIT executable | batch extraction of charge/spin grids from CHGCAR | **optional registered backend** | Useful bridge from compact VASP outputs to the volumetric viewer; acquired/configured independently and tracked by executable hash. |
| `spindensityexploration/5-3-test/isosurface.py` and generated VESTA/HTML files | exploratory isosurfaces | **reference only** | Outputs and script are experiment-specific; package later behind a validated volumetric CLI. |
| `strainEngineering/plot*.py`, `RuO2finestraintest/*`, Meinert analysis scripts | one-off plots and paper reproductions | **reference only** | Useful provenance, but overlapping scripts and hard-coded paths make them unsafe as public entry points. |

## Recommended suite boundary

The suite should own stable adapters and file contracts, not absorb every
historical script. The useful product boundary is:

1. **Structure matching:** hstructpy selects orientation, repeats, and a
   homogeneous epitaxial mapping. Treat its output report as the geometry
   provenance for a refinement run.
2. **Resource-aware DFT refinement:** EpiRefine proposes the next budgeted
   points, creates and validates relax/static inputs, safely submits them, and
   exchanges checksummed evidence between local and HPC systems.
3. **Field and local-structure inspection:** the contour renderer, hstructpy
   report, optional VASPKIT extraction hook, and polyhedron slice viewer inspect
   magnetization, energy, and local bond/volumetric changes.

This is a strong heterostructure-analysis suite because it connects lattice
matching → epitaxial strain → selective first-principles sampling → local and
field observables. It does **not** claim that geometric mismatch predicts
adhesion, reconstruction, or stable termination.

## Provenance, license, and limitations

`hstructpy` is MIT-licensed as recorded in
`grandStrainComparison/hstructpy/LICENSE`; its bundled CIF/POSCAR data retain
the provenance and attribution in `THIRD_PARTY_NOTICES.md`. EpiRefine-HPC's
adapters do not relicense or modify those files. VASP, POTCAR, and cluster
modules are external, licensed resources and must never be bundled or
redistributed by this suite.

The adaptive method is an allocation strategy, not a universal error bound:
results depend on the observable, initial design, triangulation, candidate
limits, convergence settings, and quality filters. Always retain manifests,
input hashes, DFT settings, and the iteration history. A relaxed CONTCAR is
not automatically a valid next static input; run the package audits.

## Quick integration examples

```bash
# 1. Screen a film/substrate match and save the report
epirefine interface-match substrate.cif film.vasp \
  --substrate-plane '(0001)' --film-plane '(100)' --out match.json

# 2. Build a fixed-interface coarse design; after its statics are reduced,
#    create the next adaptive proposal and relaxation scaffold
epirefine propose --input static_history.csv --out iter01_points.csv \
  --config config.json --budget 40 --iteration iter01
epirefine scaffold-relax --points iter01_points.csv --history static_history.csv \
  --source-root accepted_geometries --out iter01_relax --config config.json

# 3. Inspect a local polyhedron/volumetric result after downloading it
epirefine volume-slice --volume SPIN.vasp --output spin_slice.png
```

If `hstructpy` is maintained or moved independently, set `HSTRUCTPY_ROOT` and
record that path/version in the run manifest. This keeps the suite usable while
making external-tool changes visible rather than silently vendoring stale code.
See the [API guide](API.md) for the Python API, contour-marker bridge, dry-run behavior, and
the transparent `epirefine hstruct -- ...` passthrough.
