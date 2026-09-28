# EpiRefine-HPC

EpiRefine-HPC is an auditable workflow for adaptive two-dimensional epitaxial-strain
sampling with VASP and Slurm. It concentrates a limited calculation budget near sharp
changes in a computed response, while preserving the source geometry, sampling
decision, calculation stage, convergence evidence, and file hashes for every point.

The package supports a scriptable `epirefine` CLI and an optional guided
`epirefine-tui`. The CLI remains the authoritative interface for automation.

## Capabilities

- Generate Delaunay/gradient/zero-pocket adaptive strain proposals.
- Scaffold relaxation inputs from the nearest accepted same-plane geometry.
- Alternatively scaffold an explicitly labeled fixed-geometry static-only loop.
- Admit only audited relaxation geometries into static calculations.
- Validate, hydrate, audit, submit, and collect manifest-driven Slurm runs.
- Parse static magnetic moments and build accumulated response histories.
- Plot strain contours, sampling history, and heterostructure mismatch markers.
- Connect optional hstructpy, VASPKIT, and volumetric-slice tools through recorded
  adapters rather than bundled copies.
- Preserve checksummed provenance while excluding POTCAR and raw large VASP files
  from compact result archives.

## Quick start

Python 3.10 or newer is required.

```bash
git clone <repository-url> EpiRefine-HPC
cd EpiRefine-HPC
export PATH="$PWD/bin:$PATH"

epirefine init /path/to/RuO2-study --system RuO2
epirefine-tui --project /path/to/RuO2-study
```

For local plotting and adaptive proposals, install the scientific dependencies:

```bash
python -m pip install -e '.[analysis]'
```

A typical iteration is:

```text
accepted static history → propose → scaffold-relax → transfer to HPC
→ hydrate → validate → submit → audit → scaffold-static → submit
→ collect → transfer locally → ingest → plot → next proposal
```

If no suitable constrained-relaxation executable is available, a separate
fixed-geometry workflow is supported:

```text
direct-static history → propose → scaffold-direct-static → hydrate/validate/submit
→ collect → ingest → plot → next proposal
```

This protocol skips ionic relaxation and therefore answers a different physical
question. Do not silently mix its results with relaxed-at-target strain data.

Run `epirefine help-all` for the complete command reference and three or more examples
per command. Run `epirefine-tui --snapshot --project PROJECT` for noninteractive
project discovery.

## Assumptions and user responsibilities

- The compute environment is Unix-like and uses Slurm commands compatible with
  `sbatch` and `squeue`. Scheduler account, partition, modules, resources, and policy
  remain site-specific and must be edited in the project templates.
- VASP and all required licenses are supplied by the user or computing facility.
  EpiRefine does not distribute VASP, POTCAR, or any proprietary input.
- The user supplies and validates the relaxation and static executables named in
  `config.json`. In particular, this project does **not** provide the custom z-only
  `rlxZ` VASP binary used by the originating workflow. Users who choose that mode are
  responsible for obtaining, building, validating, and configuring their own binary.
- The included INCAR, KPOINTS, and Slurm files are editable examples, not convergence
  certificates. The user is responsible for cutoffs, k meshes, magnetic states,
  smearing, constraints, pseudopotentials, numerical convergence, and physical model
  validity.
- Local proposal and plotting operations require NumPy, SciPy, and Matplotlib.
  Interface matching additionally requires ASE and access to hstructpy.
- hstructpy, the polyhedron/volumetric slice backend, and VASPKIT are optional external
  tools. They must be acquired separately and located with the documented environment
  variables or `epirefine tool-config`.
- The TUI assumes a terminal with Python `curses`; batch and redirected work should
  use the CLI.
- Laptop/HPC exchange assumes a user-managed transfer mechanism such as `rsync` or
  `scp` and a filesystem layout that preserves manifest-relative run paths.
- Each continuous strain map assumes fixed discrete modeling choices such as
  orientation, termination, registry, composition, layer count, boundary conditions,
  and magnetic initialization. Geometrically or physically different interfaces
  should not be combined into one response surface.
- Adaptive sampling is a resource-allocation method, not an uncertainty proof or a
  replacement for independent validation points and convergence studies.

## Project inputs

`epirefine init` creates a documented project layout:

- `inputs/structures/`: reference POSCAR, CONTCAR, and CIF files.
- `inputs/kpoints/`: convergence-tested KPOINTS files.
- `templates/`: editable relaxation/static INCAR and Slurm templates.
- `data/raw/accepted_geometries/`: accepted geometries used to seed new strain points.
- `data/raw/transfers/`: unpacked HPC result archives.
- `data/processed/`: accumulated static-history CSV files.

Keep POTCAR outside the repository in secure site storage and add it through
`epirefine hydrate`.

## Documentation

- [Complete workflow](docs/WORKFLOW.md)
- [CLI reference](epirefine/data/CLI_REFERENCE.md)
- [TUI guide](docs/TUI.md)
- [Adaptive method](docs/METHOD.md)
- [Python and companion-tool API](docs/API.md)
- [Project layout](epirefine/data/PROJECT_LAYOUT.md)
- [Tool ecosystem](docs/TOOL_ECOSYSTEM.md)
- [HPC smoke-test record](docs/HPC_SMOKE_TEST.md)

This is research software. Inspect generated inputs and dry-run reports before using
computational resources or relying on scientific results.

## License

EpiRefine-HPC is released under the [MIT License](LICENSE). External programs,
scientific datasets, VASP, and POTCAR remain under their respective terms.
