# EpiRefine terminal interface

`epirefine-tui` is an optional convenience layer for interactive project inspection
and the complete EpiRefine workflow. It is installed beside `epirefine`, but the CLI
does not import it or depend on it. Scripts and reproducible batch records should
continue to use the CLI documented by `epirefine help-all`.

The interface uses Python's standard `curses` module and adds no package dependency.
It is intended for ordinary Unix terminals on a laptop or HPC login node.

## Start it

```bash
cd /path/to/an/epirefine/project
epirefine-tui
```

or point it at another project:

```bash
epirefine-tui --project /scratch/$USER/RuO2-study
```

The path may be nonexistent: use **Project setup → Initialize** to create it.
For an existing study, **Project setup → Add missing standard folders/templates** is
non-destructive and never overwrites current configuration or templates.

For noninteractive discovery, CI, or troubleshooting:

```bash
epirefine-tui --project /path/to/project --snapshot
```

The snapshot is JSON and requires neither curses nor NumPy/SciPy/Matplotlib.

## Navigation

- Up/down arrows or `j`/`k` move through menus and reports.
- Enter selects an item or closes a report.
- Page Up/Page Down scroll long reports.
- `q` or Escape returns to the preceding menu.
- Ctrl-C exits with status 130.

Text prompts accept the displayed default when submitted blank. Paths are passed
directly as subprocess arguments; the TUI never constructs a shell command.

## Where inputs and templates go

Every newly initialized project includes `PROJECT_LAYOUT.md` and this structure:

```text
inputs/structures/              bulk/reference POSCAR, CONTCAR, and CIF inputs
inputs/kpoints/                 convergence-tested KPOINTS inputs
inputs/markers/                 contour-marker CSV files
templates/relax.INCAR           editable relaxation INCAR
templates/static.INCAR          editable static INCAR
templates/relax.job.slurm       editable relaxation job script
templates/static.job.slurm      editable static job script
templates/KPOINTS               editable placeholder/default KPOINTS
data/raw/accepted_geometries/   accepted CONTCAR/POSCAR trees used to seed new points
data/raw/transfers/             unpacked HPC result archives
data/processed/                 accumulated immutable static-history CSVs
iterations/                     generated proposal/relax/static trees
```

The structure and KPOINTS directories are organizational conventions; forms still
pass explicit paths so provenance is unambiguous. The project's `templates/` files
are selected automatically whenever its `config.json` is supplied—which the guided
forms do automatically. Edit them from **Project setup → Edit**, or with `$EDITOR`.

Never store licensed POTCAR files in the project or Git. Keep POTCAR in a secure HPC
location and select it through **Run management → Hydrate**. It will be copied into
run directories and hashed in the manifest, but remains excluded from result archives.

## Complete command coverage

The guided panels expose every current `epirefine` subcommand:

| Panel | Commands |
|---|---|
| Project setup | `init` |
| Analysis/refinement | `plot`, `propose`, `ingest` |
| Scaffolding | `scaffold-relax`, `scaffold-direct-static`, `scaffold-static` |
| Run management | `hydrate`, `validate`, `audit`, `submit`, `collect` |
| External tools | `tool-status`, `tool-config` |
| Heterostructure analysis | `interface-match`, `hstruct` |
| Volumetric analysis | `extract-volumetric`, `volume-slice` |
| Built-in manual | `help-all` |

The advanced CLI console accepts any argument sequence after `epirefine`, parsed with
`shlex` and executed without a shell. This preserves access to future or uncommon
flags even before a dedicated form is added. It still requires typed confirmation for
real Slurm submission and bulk VASPKIT extraction.

## Available panels

### Project dashboard

Recursively discovers configuration, static-history CSVs, relax/static manifests,
and audit JSON files. The dashboard reports configured planes, accepted-static counts,
manifest stages and run counts, without importing scientific plotting packages.

### Static-history analysis

Summarizes total and accepted-static rows by plane and source iteration, plus the
minimum, maximum, and mean available magnetic moment. This is a quick integrity view,
not a substitute for plots or uncertainty/error analysis.

### Analysis and adaptive refinement

Select a discovered history and invoke the normal `epirefine plot` or
`epirefine propose` implementation, or ingest completed static calculations into a
new immutable history. Project `config.json` is used automatically when present. The
resulting command and complete stdout/stderr remain visible in the TUI.

### Relax/static scaffolding

The relaxation form selects the proposal CSV, accepted static history, geometry source
root, output, and optional site inputs. The static form selects the relaxation
manifest/results and applies the same optional POTCAR/KPOINTS handling. Both default
to dry-run so paths and decisions can be inspected before full input trees are made.

The direct-static form uses proposals and accepted geometries but skips ionic
relaxation entirely. It is intended for a consistently fixed-geometry study when no
suitable constrained-relaxation executable is available. Its results are explicitly
tagged and should not be silently mixed with relaxed-at-target points.

### Run manifest management

After selecting a relax/static manifest, the menu can:

- inspect its stage, plane distribution, accepted run count, and rejections;
- hydrate POTCAR/KPOINTS with optional moved-root handling;
- validate scaffold files and hashes;
- audit run completion and save a JSON report;
- preview duplicate-safe Slurm submission;
- submit after the user types the exact confirmation word `SUBMIT`;
- scaffold statics from a relax manifest; or
- preview/create the normal checksummed transfer archive, optionally running VASPKIT
  extraction with registry, timeout, and replacement controls.

Submission preview and actual submission are deliberately separate. The TUI cannot
bypass CLI validation, duplicate protection, sticky claims, or `--execute` semantics.

### External tools and volumetric analysis

The external-tools panel runs `tool-status` and can register an independently acquired
VASPKIT executable. The VASPKIT panel supports task 311 charge, task 312 spin, and task
313 spin-component extraction, with dry-run as a distinct menu choice and the exact
confirmation word `EXTRACT` before real bulk extraction.

The volume-slice form exposes datasets, atom selections, isolevels, grid/extent,
colormap, transforms, tolerances, reports, and dry-run/render choice. The typed
interface-mismatch form exposes planes, layers, repeats, axis swaps, and marker output.
The hstructpy passthrough provides its complete build/batch/domain-search/GUI surface.

### Full CLI manual and advanced console

The complete packaged CLI reference can be read inside the interface. The advanced
console is the explicit escape hatch for new or uncommon arguments.

## Installation behavior

Normal Python installation creates both commands:

```bash
python -m pip install -e '.[analysis]'
epirefine --help
epirefine-tui --help
```

The dependency-free source installer also links both commands:

```bash
./install.sh
```

For the intended HPC checkout workflow, adding the checkout's `bin` directory to PATH
exposes both without installation:

```bash
export PATH="$HOME/software/EpiRefine-HPC/bin:$PATH"
```

## Scope, limitations, and safety

The TUI covers the full current command set but remains a front end, not a second
workflow engine. All operations execute
`python -m epirefine.cli` without a shell, so argument quoting cannot become shell
execution. The screen shows the exact delegated command and captured output.

No action runs merely by opening the interface. Plotting/proposals/scaffolding write
only after their forms are submitted; submission and VASPKIT bulk extraction require
typed confirmation. POTCAR licensing and archive-exclusion rules are unchanged.

If a terminal is noninteractive, the program refuses to initialize curses and points
the user to `--snapshot`. Use the ordinary CLI for batch scripts, redirected jobs,
automation, and provenance command logs.

Other practical limitations:

- long-running post-processing blocks the TUI until the delegated command finishes;
- captured output is shown after completion rather than streamed continuously;
- narrow/minimal terminals may be less comfortable than the CLI;
- file prompts are path-based, not a graphical filesystem browser;
- `$EDITOR` must name an available terminal editor for in-TUI template editing;
- hstructpy GUI operation still requires a graphical display/Tk environment;
- scientific dependencies and external executables remain command-specific; the TUI
  does not install them, VASPKIT, VASP, POTCAR, or scheduler modules;
- a form cannot decide scientific convergence settings—the user must edit and validate
  the project templates and convergence-tested KPOINTS/POTCAR choices.
