# EpiRefine-HPC workflow guide

EpiRefine-HPC is a small, auditable workflow for spending a limited first-principles
compute budget on the most informative parts of a two-dimensional epitaxial-strain
map. It connects local proposal generation and plotting to relaxation/static VASP
runs on Slurm, while keeping every selection, geometry source, checksum, and rejected
calculation visible.

The primary interface is one command, `epirefine`, on both the laptop and HPC. The
historical `StrainContour` workflow is not imported, moved, or modified by this
package. EpiRefine is a reusable distillation of that workflow, not a claim that the
underlying adaptive-sampling ideas are novel.

The compact mathematical specification is in [`METHOD.md`](METHOD.md).
The no-submit Expanse validation record is in
[`HPC_SMOKE_TEST.md`](HPC_SMOKE_TEST.md).
The unified terminal/Python interface for mismatch analysis, contour markers,
adaptive refinement, and volumetric slicing is in [`API.md`](API.md).
The packaged exhaustive CLI manual, with three examples for every command, is
[`CLI_REFERENCE.md`](../epirefine/data/CLI_REFERENCE.md) and is printed by
`epirefine help-all`.
An optional guided terminal interface is documented in [`TUI.md`](TUI.md).

```bash
epirefine-tui --project /path/to/project
epirefine-tui --project /path/to/project --snapshot
```

The TUI is installed beside the CLI and uses only the standard library. It delegates
all work to `epirefine`, so the CLI remains the complete, automation-friendly source
of truth and works independently of the interface.

## One heterostructure-analysis command surface

`epirefine` is also the front door to the companion analysis tools in this research
checkout. Their implementations remain independent and traceable; EpiRefine provides
typed adapters and records backend versions or hashes.

```bash
epirefine tool-status
epirefine interface-match substrate.cif film.vasp \
  --substrate-plane '(0001)' --film-plane '(100)' \
  --out reports/match.json --marker-out data/marker.csv \
  --marker-plane 100 --marker-label 'Al2O3(0001)'
epirefine hstruct -- domain-search substrate.cif film.vasp --max-strain 10 --json
epirefine volume-slice --volume SPIN.vasp --output plots/spin_slice.png --dry-run
epirefine help-all
```

Set `HSTRUCTPY_ROOT` or `POLYHEDRON_SLICE_ROOT` when those tools are not siblings of
the EpiRefine checkout. Install `.[analysis]` for the complete local scientific
dependency set. None of these commands copy, alter, or conceal the original tools.

VASPKIT is an optional external backend for producing viewer-ready charge/spin
volumes from retained CHGCAR files. Acquire and configure VASPKIT independently;
EpiRefine does not download or bundle it:

```bash
epirefine tool-config vaspkit --path /absolute/path/to/vaspkit
epirefine extract-volumetric --root iterations/iter01/static \
  --products charge spin --dry-run
epirefine collect --root iterations/iter01/static --archive iter01_static.tar.gz \
  --vaspkit-extract charge spin
```

The collection hook uses VASPKIT tasks 311 (charge), 312 (spin), and optionally
313 (spin-up/down), checks output collisions, records executable/output hashes, and
archives the derived volumes while continuing to exclude CHGCAR and POTCAR.

## What it does

```text
accepted static data
        │
        ├─ plot ───────────────────────────────> 3-panel contours + history
        │
        └─ propose (Delaunay mesh) ────────────> budgeted points + decision record
                               │
                    scaffold-relax (nearest accepted CONTCAR, strained a/b)
                               │
                    rsync project to HPC
                               │
          hydrate → validate → submit → audit → scaffold-static
                               │
                  validate → submit → audit → collect
                               │
                    rsync archive to laptop
                               │
                     checksum → ingest ─────────> next accepted static data
```

Relaxation magnetic moments are never admitted as final scientific values. A static
manifest is mandatory for ingestion. Incomplete/fatal OUTCARs remain explicit
`incomplete` rows rather than silently becoming zero.

If an ionic-relaxation executable is unavailable, EpiRefine also supports a separate
fixed-geometry loop:

```text
accepted direct-static geometries -> propose -> scaffold-direct-static
                                  -> hydrate -> validate -> submit -> ingest
```

This route does not reproduce the relaxed-strain protocol. It affinely strains the
first two lattice vectors of the nearest accepted same-plane geometry while preserving
fractional coordinates and the third vector, then runs a static calculation. Keep its
results in a separate history with `geometry_protocol=direct_static`; mixing them with
`relaxed_static` points can create artificial response jumps.

## Use the checkout on the laptop and HPC

Python 3.10+ is required. Local proposal/plot commands need NumPy, SciPy, and
Matplotlib; HPC setup, validation, submission, audit, and collection do not.

Clone the package independently on each machine. On Expanse, keep it in a
stable path and manually add its `bin` directory to your shell path:

```bash
# Expanse: replace URL with the eventual repository URL.
git clone REPOSITORY_URL ~/software/EpiRefine-HPC

# Test for the current shell.
export PATH="$HOME/software/EpiRefine-HPC/bin:$PATH"
epirefine --help

# After inspection, place that export line in ~/.bashrc yourself.
```

No cluster-side pip installation is required for `scaffold-*`, `hydrate`,
`validate`, `submit`, `audit`, or `collect`. EpiRefine never edits `.bashrc`,
and this workflow intentionally leaves PATH management to the user. Expanse is
not expected to use `shell.nix`; use its normal Python 3.10+ and environment
modules.

On the laptop, either expose the checkout in the same way or use an editable
environment with the plotting/proposal dependencies:

```bash
python -m venv .venv
.venv/bin/pip install -e '.[local]'
source .venv/bin/activate
epirefine --help
```

On a NixOS laptop, the included pinned environment is the shortest route:

```bash
cd EpiRefine-HPC
nix-shell
epirefine --help
```

If local pip/build tooling is unavailable, the dependency-free source installer
creates safe `epirefine` and `epirefine-tui` symlinks to the checkout:

```bash
./install.sh
epirefine --help
```

It refuses to replace an existing command. `propose` and `plot` still require
NumPy/SciPy/Matplotlib. A normal pip installation includes all templates, but
the intended Expanse deployment is a Git checkout plus manual PATH routing.

## One complete iteration

### 1. Initialize and configure locally

```bash
epirefine init ~/epirefine/RuO2
cd ~/epirefine/RuO2
$EDITOR config.json
$EDITOR templates/relax.INCAR
$EDITOR templates/static.INCAR
$EDITOR templates/relax.job.slurm
$EDITOR templates/static.job.slurm
```

Initialization also creates `inputs/structures/` for reference POSCAR/CONTCAR/CIF
files, `inputs/kpoints/` for convergence-tested meshes, `inputs/markers/` for contour
overlays, `data/raw/accepted_geometries/` for scaffold source geometries, and
`data/raw/transfers/` for unpacked HPC archives. The generated `PROJECT_LAYOUT.md`
documents every directory. Keep POTCAR outside the project in secure HPC storage and
add it with `epirefine hydrate`.

For an existing nonempty project, add only missing standard directories and files
without replacing current templates or configuration:

```bash
epirefine init /path/to/existing/project --ensure-layout
```

The project templates are conservative examples, not convergence-certified
settings. Review `ENCUT`, k mesh, smearing, magnetic initialization, dipole/spin-orbit
settings, force tolerance, scheduler account/partition, modules, ranks, memory, and
walltime for the actual material and cluster.

The originating RuO2/Expanse settings are preserved as an optional, auditable
example in `examples/ruo2_pbe_afm_expanse/`; they are not silently imposed on
other materials.

The two stages have independent `relax_vasp_command` and
`static_vasp_command` entries in `config.json`. This supports, for example, a
custom z-only relaxation executable followed by ordinary VASP statics without
manual script rewriting. EpiRefine does not distribute the custom `rlxZ` binary:
the user must supply, validate, and configure any such executable for their VASP
installation and computing site.

Seed `data/processed/static_history.csv` with one row per completed static calculation.
Required fields are:

```csv
plane,eps_a_percent,eps_b_percent,ru_mean_abs_muB,parse_status,source_type,relax_contcar,run_dir,source_iteration
001,-10,-10,0.0,ok,coarse_static,initial/001/m10_m10/CONTCAR,initial/001/m10_m10,initial
```

`source_type` or `calculation_stage` must explicitly contain `static`. `relax_contcar`
may be absolute or relative to the later `--source-root`. Legacy files that mix
qualified-relax and static rows are safe to use: only explicitly static rows enter
proposal generation or plots.

For a heterostructure, each refinement map must hold termination, stacking/registry,
layer count, composition, magnetic initialization, and boundary conditions fixed.
Record those choices beside the project and in provenance. Do not triangulate across
different discrete interface constructions as if they were points on one smooth
strain surface.

### 2. Plot and propose locally

```bash
epirefine plot \
  --input data/processed/static_history.csv \
  --out plots/iter00 \
  --planes 001 100 110

epirefine propose \
  --input data/processed/static_history.csv \
  --out iterations/iter01/proposed_points.csv \
  --config config.json \
  --budget 50 \
  --iteration iter01
```

`plot` writes a common-scale side-by-side contour PNG/PDF, a sampling-history plot,
and `plot_metadata.json`. Interpolation is piecewise linear over a Delaunay
triangulation; white dots remain the actual calculations.

`propose` evaluates triangle diameter, response span, a dimensionless triangle-quality
measure, and a local edge-gradient proxy. A response triangle remains unresolved when
it is large enough and either crosses the configured low/high moment thresholds or
spans the configured minimum response. Candidates are maximin interior points, not
arbitrary offsets. Connected low-moment vertex components that do not touch the convex
hull receive a zero-pocket confirmation candidate. Spacing, bounds, total budget,
input checksum, rules, and every source triangle are recorded in CSV/JSON.

Only planes listed in `config.json` are eligible for new proposals. Remove a
converged/control plane there while continuing to retain it in plots. To overlay
heterostructure mismatch locations, add `--markers epitaxial_markers.csv` to
`epirefine plot`; the marker file uses
`plane,eps_a_percent,eps_b_percent,label` columns. Existing hstructpy-style
files using `ruo2_plane`, `substrate`, and `substrate_plane` are also accepted.

Inspect the proposals before scaffolding. A recommendation is an allocation strategy,
not an uncertainty bound or proof of a phase boundary.

### 3. Create relaxation or direct-static inputs locally

```bash
# Preview first; this still writes only the manifest in a new output directory.
epirefine scaffold-relax \
  --points iterations/iter01/proposed_points.csv \
  --history data/processed/static_history.csv \
  --source-root data/raw/accepted_geometries \
  --out iterations/iter01/relax_preview \
  --config config.json \
  --dry-run

# Create a fresh real directory after review.
epirefine scaffold-relax \
  --points iterations/iter01/proposed_points.csv \
  --history data/processed/static_history.csv \
  --source-root data/raw/accepted_geometries \
  --out iterations/iter01/relax \
  --config config.json
```

For each proposal EpiRefine selects the nearest accepted static point in the same
plane, locates its relaxation CONTCAR, preserves Direct coordinates and the relaxed
third lattice vector, and rescales the first two lattice vectors from the source
strain to the target strain. The source/target strains, geometry checksum, lattice
scale, files, and hashes are written to `relax_manifest.json`.

If a licensed POTCAR is available locally, pass `--potcar /secure/POTCAR`. Otherwise
the scaffold contains `POTCAR_REQUIRED` and is intentionally not submission-ready.
The packaged KPOINTS template is only a placeholder; pass `--kpoints` for a
convergence-checked mesh.

For a consistently fixed-geometry study, skip the relaxation stage and create static
directories directly from the proposal CSV:

```bash
# Preview the source geometries and generated manifests.
epirefine scaffold-direct-static \
  --points iterations/iter01/proposed_points.csv \
  --history data/processed/direct_static_history.csv \
  --source-root data/raw/accepted_geometries \
  --out iterations/iter01/static_preview \
  --config config.json \
  --dry-run

# Create the submission-ready layout; POTCAR/KPOINTS may instead be hydrated on HPC.
epirefine scaffold-direct-static \
  --points iterations/iter01/proposed_points.csv \
  --history data/processed/direct_static_history.csv \
  --source-root data/raw/accepted_geometries \
  --out iterations/iter01/static \
  --config config.json
```

This writes `static_manifest.json` immediately, so omit the later
`scaffold-static` conversion step. Hydrate, validate, submit, audit, collect, and
ingest it as an ordinary static manifest. The source geometries should share one
consistent construction/reference protocol; switching source relaxation histories
inside a direct-static map can itself introduce discontinuities.

### 4. Transfer the project to HPC, hydrate, validate, and submit

From the laptop:

```bash
rsync -avP --checksum \
  ~/epirefine/RuO2/ \
  user@hpc:/scratch/$USER/epirefine/RuO2/
```

On the HPC:

```bash
cd /scratch/$USER/epirefine/RuO2

# Add cluster-licensed/site-specific inputs and update manifest hashes.
epirefine hydrate \
  --manifest iterations/iter01/relax/relax_manifest.json \
  --potcar /secure/potcars/RuO2/POTCAR \
  --kpoints /path/to/converged/KPOINTS \
  --replace-kpoints

epirefine validate --manifest iterations/iter01/relax/relax_manifest.json

# Preview is the default and performs no submission.
epirefine submit --manifest iterations/iter01/relax/relax_manifest.json

# Explicit scheduler mutation:
epirefine submit --manifest iterations/iter01/relax/relax_manifest.json --execute
epirefine audit \
  --manifest iterations/iter01/relax/relax_manifest.json \
  --out iterations/iter01/relax_audit.json
```

Submission is duplicate-aware: it validates hashes first, recognizes numeric job
markers and existing outputs, reconciles Slurm working directories, and uses an
exclusive sticky claim. If submission is interrupted, inspect scheduler history
before removing `.epirefine-submitting`; the scheduler may have accepted the job.

### 5. Audit relaxations and create statics

Run this on either machine where the transferred relaxation OUTCAR/CONTCAR files live:

```bash
epirefine scaffold-static \
  --relax-manifest iterations/iter01/relax/relax_manifest.json \
  --relax-results iterations/iter01/relax \
  --out iterations/iter01/static \
  --config config.json \
  --potcar /secure/potcars/RuO2/POTCAR \
  --kpoints /path/to/converged/KPOINTS

epirefine validate --manifest iterations/iter01/static/static_manifest.json
epirefine submit --manifest iterations/iter01/static/static_manifest.json
epirefine submit --manifest iterations/iter01/static/static_manifest.json --execute
epirefine audit \
  --manifest iterations/iter01/static/static_manifest.json \
  --out iterations/iter01/static_audit.json
```

Static directories are created only from relaxations with a parseable nonempty
CONTCAR, VASP's ionic-convergence marker, no known fatal signature, and a normal timing
footer. Rejected relaxations are listed in the static manifest. No static is silently
created from an unconverged geometry.

### 6. Collect on HPC and transfer back

On the HPC:

```bash
epirefine collect \
  --root iterations/iter01 \
  --archive /scratch/$USER/epirefine_iter01_results.tar.gz \
  --dry-run

epirefine collect \
  --root iterations/iter01 \
  --archive /scratch/$USER/epirefine_iter01_results.tar.gz
```

The compatibility wrapper `hpc/collect_outcars.sh RUN_ROOT ARCHIVE` calls the same CLI.
The archive contains OUTCAR/OSZICAR/CONTCAR/POSCAR, nonlicensed inputs, manifests, and
SHA-256 sums. POTCAR is deliberately excluded.

From the laptop:

```bash
mkdir -p ~/epirefine/RuO2/data/raw/iter01_transfer
rsync -avP user@hpc:/scratch/$USER/epirefine_iter01_results.tar.gz \
  ~/epirefine/RuO2/data/raw/
tar -xzf ~/epirefine/RuO2/data/raw/epirefine_iter01_results.tar.gz \
  -C ~/epirefine/RuO2/data/raw/iter01_transfer
cd ~/epirefine/RuO2/data/raw/iter01_transfer
sha256sum -c metadata/SHA256SUMS
```

Use `rsync -avP` instead of starting over after a network interruption. `--checksum`
is useful for the smaller project/manifests transfer; the archive already has its own
checksums.

### 7. Ingest static results and begin the next iteration locally

```bash
cd ~/epirefine/RuO2
epirefine ingest \
  --results data/raw/iter01_transfer/results/static \
  --manifest data/raw/iter01_transfer/results/static/static_manifest.json \
  --history data/processed/static_history.csv \
  --out data/processed/static_history_iter01.csv \
  --config config.json

epirefine plot \
  --input data/processed/static_history_iter01.csv \
  --out plots/iter01 \
  --planes 001 100 110

epirefine propose \
  --input data/processed/static_history_iter01.csv \
  --out iterations/iter02/proposed_points.csv \
  --config config.json \
  --budget 40 \
  --iteration iter02
```

The ingested rows retain the absolute path of the static POSCAR, which is the
audited relaxed geometry used by that static calculation. Keep transferred
result directories in place; `scaffold-relax` can then select the nearest
accepted geometry directly from the accumulated history. Historical tables
using `relax_source_relpath` are also understood when the corresponding
CONTCAR tree is supplied through `--source-root`.

If the archive's preserved relative paths differ, point `--results` at the directory
that contains the static run tree and `--manifest` at its static manifest. Resolution
uses exact relative paths first and a unique run-directory suffix second; ambiguous
matches fail closed.

## Scientific method and resource constraints

The defensible workflow is:

1. Start from a convergence-tested, space-filling coarse design covering the declared
   strain domain. Do not seed only where an expected transition should occur.
2. Freeze thresholds and a per-iteration budget before seeing the new outcomes.
3. Allocate points to unresolved response triangles and enclosed low-moment pockets.
4. Reserve independent validation points when quantitative stopping error matters;
   targeted points alone do not provide an unbiased error estimate.
5. Use consistent static calculations for the response surface. Treat relaxation
   moments only as quality diagnostics.
6. Stop when the predeclared resolution/error criterion is met or the compute budget
   is exhausted, and report which condition ended sampling.

The approach can reduce calculations when sharp structure occupies a small part of a
2-D domain, but it can miss features absent from the initial mesh, is observable-
dependent, and inherits all DFT/systematic errors. Delaunay interpolation can be poor
near sparse convex-hull edges and sliver triangles. Validate magnetic order, cell size,
k mesh, cutoff, smearing, relaxation constraints, interface termination, and competing
structures before assigning a physical phase boundary.

## Provenance and safety contract

- Scaffold commands refuse an existing output directory.
- Proposal, scaffold, ingest, plot, hydration, validation, and archive records contain
  input or output hashes where applicable.
- Duplicate accepted coordinates fail instead of being silently averaged or replaced.
- `submit` is a preview unless `--execute` is stated.
- Existing outputs/job markers are never overwritten by submission.
- Static handoff fails individual relaxations closed and records every rejection.
- Ingestion requires a static manifest and species-aware POSCAR indexing; it does not
  assume the first four atoms are Ru.
- POTCAR is never packaged in transfer archives.

Keep accepted CSVs immutable. Write a new history file for each iteration, retain the
proposal JSON, manifests, audit JSON, archive checksum, config/templates, environment
lock or package version, and the exact commands in `provenance/`.

## Companion heterostructure-analysis tools

The suite boundary is deliberately narrow. See `TOOL_ECOSYSTEM.md` for the full
inventory and rationale.

- `epirefine interface-match` and `epirefine hstruct -- ...` expose the existing
  MIT-licensed `hstructpy` surface orientation, coincidence/domain matching,
  finite-strain report, and heterostructure builder. Reports are suitable geometry
  provenance before EpiRefine sampling.
- `epirefine plot` is the consolidated contour/history viewer for accepted scalar
  strain data.
- `epirefine volume-slice` provides a provenance-recording static renderer around the
  existing local polyhedron/volumetric slice tool for bond, interface, and
  spin/charge-density inspection.

These tools remain separately versioned and are accessed through adapters; EpiRefine
does not copy their implementations. This avoids turning experiment-specific scripts
into an unmaintainable monolith. `hstructpy` establishes a plausible periodic geometry,
but geometric matching alone does not establish adhesion, reconstruction, termination
stability, or an electronic ground state.

## Development and tests

```bash
python -m compileall -q epirefine bin tools tests
python -m unittest discover -s tests -v
bash -n hpc/collect_outcars.sh
```

The end-to-end test constructs synthetic static history, proposes points, strains the
nearest CONTCAR, validates and dry-runs submission, audits relaxation-to-static
handoff, parses species-aware static moments, and verifies that the transfer archive
contains checksums but no POTCAR.

The single supported command entry point is `bin/epirefine` (or `epirefine`
after PATH setup). All workflow stages are subcommands of that interface.
