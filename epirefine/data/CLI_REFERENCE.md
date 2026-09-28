# EpiRefine command reference

This is the complete command-line reference for EpiRefine-HPC 0.4.0. Run
`epirefine COMMAND --help` for the compact parser-generated option list or
`epirefine help-all` to print this file. Paths may be relative or absolute.

Unless explicitly stated otherwise, commands print a JSON result to standard output.
Scientific arrays use strain in percent. Plane labels such as `001` are normalized
without parentheses. `submit` is non-mutating unless `--execute` is present, and
POTCAR is never placed in a transfer archive.

## `init`

Create a new project with input, data, iteration, plot, provenance, and editable
template directories. The target must be absent or empty. `--system` overrides the
default system label written to a new `config.json`. `--ensure-layout` may be used on
an existing project; it creates only missing standard directories/files and never
overwrites an existing config, template, or layout guide.

```bash
epirefine init RuO2-study --system RuO2
```

```bash
epirefine init "$PWD/projects/interface-a" --system 'RuO2/Al2O3'
```

```bash
epirefine init /scratch/$USER/epirefine-demo
```

```bash
epirefine init existing-study --ensure-layout
```

## `propose`

Generate the next Delaunay/gradient/zero-pocket sampling proposal from accepted static
data. `--input` is the accumulated static-history CSV, `--out` is the new proposal
CSV, `--config` supplies thresholds and eligible planes, `--budget` overrides its
point budget, and `--iteration` becomes the provenance label.

```bash
epirefine propose --input data/processed/static_history.csv \
  --out iterations/iter01/proposed_points.csv --config config.json \
  --budget 50 --iteration iter01
```

```bash
epirefine propose --input static_history_iter01.csv \
  --out iter02_points.csv --config config.json --iteration iter02
```

```bash
epirefine propose --input accepted_statics.csv --out preview.csv \
  --budget 12 --iteration sensitivity-check
```

## `scaffold-relax`

Create one relaxation directory per proposed point by selecting the nearest accepted
same-plane geometry and rescaling its a/b lattice vectors. `--source-root` resolves
relative geometry paths. `--config` selects project templates and VASP command.
`--potcar` and `--kpoints` are optional site inputs. `--dry-run` writes only a
manifest in a new output directory.

```bash
epirefine scaffold-relax --points iterations/iter01/proposed_points.csv \
  --history data/processed/static_history.csv --source-root data/raw \
  --out iterations/iter01/relax --config config.json
```

```bash
epirefine scaffold-relax --points proposed.csv --history history.csv \
  --source-root accepted_geometries --out relax_preview --config config.json --dry-run
```

```bash
epirefine scaffold-relax --points proposed.csv --history history.csv \
  --source-root transferred_results --out relax --config config.json \
  --potcar /secure/potcars/RuO2/POTCAR --kpoints converged.KPOINTS
```

## `scaffold-direct-static`

Create static calculations directly from proposed points without an ionic-relaxation
stage. Each POSCAR is produced by affinely scaling the a/b vectors of the nearest
accepted same-plane static geometry while preserving fractional coordinates and the
third lattice vector. Static INCAR/job templates and `static_vasp_command` are used;
the output is immediately a `static_manifest.json` suitable for validation,
submission, ingestion, plotting, and the next proposal.

This is a fixed-geometry response protocol, not a substitute that reproduces relaxed
epitaxial strain. Use one consistent geometry protocol for the complete response map
and retain the `geometry_protocol` column. Mixing direct-static points with
relaxed-at-target points can create artificial response discontinuities.

```bash
epirefine scaffold-direct-static \
  --points iterations/iter01/proposed_points.csv \
  --history data/processed/direct_static_history.csv \
  --source-root data/raw/accepted_geometries \
  --out iterations/iter01/static_direct --config config.json --dry-run
```

```bash
epirefine scaffold-direct-static --points proposed.csv --history direct_history.csv \
  --source-root accepted_geometries --out static_direct --config config.json \
  --kpoints inputs/kpoints/KPOINTS
```

```bash
epirefine scaffold-direct-static --points proposed.csv --history direct_history.csv \
  --source-root transferred_results --out static_direct --config config.json \
  --potcar /secure/potcars/RuO2/POTCAR --kpoints converged.KPOINTS
```

## `scaffold-static`

Audit relaxation completion and build static directories only from accepted CONTCARs.
The relaxation manifest fixes identities and coordinates; `--relax-results` locates
the actual result tree. Rejections are recorded rather than hidden. `--dry-run`
produces the decision manifest without run inputs.

```bash
epirefine scaffold-static --relax-manifest iterations/iter01/relax/relax_manifest.json \
  --relax-results iterations/iter01/relax --out iterations/iter01/static \
  --config config.json
```

```bash
epirefine scaffold-static --relax-manifest relax_manifest.json \
  --relax-results downloaded_relax --out static_preview --config config.json --dry-run
```

```bash
epirefine scaffold-static --relax-manifest relax/relax_manifest.json \
  --relax-results relax --out static --config config.json \
  --potcar /secure/potcars/RuO2/POTCAR --kpoints converged.KPOINTS
```

## `ingest`

Reduce completed static OUTCARs into the next static-history CSV. A static manifest is
mandatory. `--history` appends to an existing accepted history without overwriting it;
`--config` selects the atomic species used for mean absolute magnetic moment.

```bash
epirefine ingest --results data/raw/iter01/static \
  --manifest data/raw/iter01/static/static_manifest.json \
  --history data/processed/static_history.csv \
  --out data/processed/static_history_iter01.csv --config config.json
```

```bash
epirefine ingest --results static --manifest static/static_manifest.json \
  --out first_static_history.csv --config config.json
```

```bash
epirefine ingest --results transferred/results/static \
  --manifest transferred/results/static/static_manifest.json \
  --history accepted.csv --out accepted_plus_iter03.csv
```

## `plot`

Render common-scale side-by-side strain contours and the sampling-history audit.
Only explicitly accepted static rows enter the response surface. `--planes` controls
panel order; `--markers` overlays a mismatch-marker CSV.

```bash
epirefine plot --input data/processed/static_history.csv \
  --out plots/current --planes 001 100 110
```

```bash
epirefine plot --input accepted.csv --out plots/interfaces \
  --planes 001 100 110 --markers data/epitaxial_markers.csv
```

```bash
epirefine plot --input static_history_iter03.csv --out plots/iter03 --planes 001 100
```

## `validate`

Verify scaffold structure, required files, and recorded hashes before submission.
`--root` overrides the manifest directory when a tree has been moved.

```bash
epirefine validate --manifest iterations/iter01/relax/relax_manifest.json
```

```bash
epirefine validate --manifest manifests/static_manifest.json \
  --root /scratch/$USER/RuO2/iter01/static
```

```bash
epirefine hydrate --manifest relax/relax_manifest.json --potcar /secure/POTCAR && \
  epirefine validate --manifest relax/relax_manifest.json
```

## `hydrate`

Add licensed/site-specific POTCAR and/or KPOINTS files to every scaffolded run and
update their manifest hashes. Existing KPOINTS are preserved unless
`--replace-kpoints` is supplied. POTCAR is still excluded by `collect`.

```bash
epirefine hydrate --manifest relax/relax_manifest.json \
  --potcar /secure/potcars/RuO2/POTCAR
```

```bash
epirefine hydrate --manifest static/static_manifest.json \
  --potcar /secure/POTCAR --kpoints /shared/KPOINTS --replace-kpoints
```

```bash
epirefine hydrate --manifest manifests/static_manifest.json \
  --root /scratch/$USER/study/static --kpoints ./KPOINTS.converged
```

## `audit`

Classify every manifest run as not started, queued, complete, or incomplete using
stage-appropriate evidence. `--out` preserves the JSON audit in addition to printing
it. `--root` handles moved trees.

```bash
epirefine audit --manifest relax/relax_manifest.json --out relax_audit.json
```

```bash
epirefine audit --manifest static/static_manifest.json --root static
```

```bash
epirefine audit --manifest transferred/static_manifest.json \
  --root transferred/results/static --out provenance/post_transfer_audit.json
```

## `submit`

Preview or submit duplicate-safe Slurm jobs. Preview is the default. `--execute` is
required for `sbatch`; `--limit` caps newly planned/submitted jobs. Existing job IDs,
outputs, scheduler working directories, and sticky submission claims prevent casual
duplicates.

```bash
epirefine submit --manifest relax/relax_manifest.json
```

```bash
epirefine submit --manifest relax/relax_manifest.json --execute --limit 1600
```

```bash
epirefine validate --manifest static/static_manifest.json && \
  epirefine submit --manifest static/static_manifest.json --root static --execute
```

## `collect`

Create a checksummed HPC-to-local archive of compact run evidence. `--dry-run` lists
contents without extracting volumes or creating an archive. With `--vaspkit-extract`,
the command first processes every recursive CHGCAR through configured VASPKIT tasks:
`charge`=311, `spin`=312, and `spin-components`=313. Viewer-ready products and the
extraction report enter the archive; raw CHGCAR and POTCAR do not. Existing products
are skipped unless `--vaspkit-replace` is explicit. `--vaspkit-timeout` applies to
each task, and `--tool-registry` selects a nondefault external-tool registry.

```bash
epirefine collect --root iterations/iter01 \
  --archive /scratch/$USER/iter01_results.tar.gz --dry-run
```

```bash
epirefine collect --root iterations/iter01/static \
  --archive /scratch/$USER/iter01_static.tar.gz \
  --vaspkit-extract charge spin --vaspkit-timeout 900
```

```bash
epirefine collect --root static --archive static_with_spin_parts.tar.gz \
  --vaspkit-extract spin-components --tool-registry ./tools.json
```

## `tool-status`

Report native API availability and locate hstructpy, the volume-slice backend, and
VASPKIT. `--tool-registry` overrides the user registry; `--out` saves the report.
Discovery never executes an external tool.

```bash
epirefine tool-status
```

```bash
epirefine tool-status --out provenance/tool_status.json
```

```bash
EPIREFINE_TOOL_REGISTRY=$PWD/tools.json epirefine tool-status \
  --out provenance/portable_tools.json
```

## `tool-config`

Register an independently acquired executable. EpiRefine neither downloads nor
installs VASPKIT. The executable must already exist and be executable. The default
registry is `~/.config/epirefine/tools.json`; `--tool-registry` makes configuration
project- or cluster-specific. `VASPKIT_BIN` can instead provide a temporary override.

```bash
epirefine tool-config vaspkit --path /opt/vaspkit/bin/vaspkit
```

```bash
epirefine tool-config vaspkit --path "$HOME/software/vaspkit/bin/vaspkit" \
  --tool-registry "$HOME/.config/epirefine/expanse-tools.json"
```

```bash
epirefine tool-config vaspkit --path ./external/vaspkit \
  --tool-registry ./provenance/tools.json
```

## `extract-volumetric`

Run VASPKIT noninteractively in every directory below `--root` containing CHGCAR.
`--products` accepts charge, spin, and spin-components. `--dry-run` resolves VASPKIT
and reports planned tasks without invoking it. `--replace` permits preexisting output
replacement; otherwise collisions are recorded and skipped. `--timeout` is per task.
The real run writes `.epirefine-vaspkit.json` at the root; `--out` writes another copy.

```bash
epirefine extract-volumetric --root iterations/iter01/static \
  --products charge spin --dry-run
```

```bash
epirefine extract-volumetric --root static --products spin-components \
  --timeout 900 --out provenance/vaspkit_static.json
```

```bash
epirefine extract-volumetric --root copied_single_run --products charge \
  --tool-registry ./tools.json --replace
```

## `interface-match`

Use hstructpy to orient a substrate and film and calculate intrinsic in-plane lattice
mismatch. Plane strings accept three-index or hexagonal four-index notation. Layer,
axis-swap, and repeat flags make the surface convention explicit. `--out` is the
full JSON report. `--marker-out` also requires `--marker-plane` and `--marker-label`
and writes a contour-ready one-row CSV.

```bash
epirefine interface-match cells/TiO2.vasp cells/RuO2.vasp \
  --substrate-plane '(110)' --film-plane '(110)' --out reports/tio2_110.json
```

```bash
epirefine interface-match cells/Al2O3.cif cells/RuO2.vasp \
  --substrate-plane '(0001)' --film-plane '(100)' --substrate-swap-axes \
  --out reports/sapphire.json --marker-out data/sapphire_marker.csv \
  --marker-plane 100 --marker-label 'Al2O3(0001)'
```

```bash
epirefine interface-match substrate.vasp film.vasp \
  --substrate-layers 2 --film-layers 2 --substrate-repeats 2 1 \
  --film-repeats 3 1 --film-swap-axes --out reports/domain.json
```

## `hstruct`

Pass arbitrary arguments through to the independently maintained hstructpy CLI. Use
`--` so its options are not interpreted by EpiRefine. This exposes domain searches,
batch comparison, interface building, and the GUI without copying their code.

```bash
epirefine hstruct -- domain-search substrate.cif film.vasp --max-strain 10 --json
```

```bash
epirefine hstruct -- build substrate.cif film.vasp interface.vasp \
  --substrate-plane '(0001)' --top-plane '(100)' --gap 3.0 --vacuum 18
```

```bash
epirefine hstruct -- batch film.vasp substrate1.cif substrate2.cif \
  --top-plane '(110)' --csv reports/batch.csv
```

## `volume-slice`

Render a static planar slice using the existing polyhedron slice backend. Select the
VASP volume block with `--dataset`, central and ligand atoms with `--center`,
`--poly-atoms`, and exactly three `--plane-atoms`, and resolution/extent with
`--grid-points`, `--padding`, and `--span`. Color controls include `--cmap`,
`--value-transform`, `--log-floor`, `--isolevels`, and `--no-symmetric-color`.
`--report` saves backend/output hashes. `--dry-run` does not read the volume.

```bash
epirefine volume-slice --volume SPIN.vasp --output plots/spin_slice.png \
  --center Ru2 --plane-atoms Ru2 O2 O5 --report provenance/spin_slice.json
```

```bash
epirefine volume-slice --volume CHARGE.vasp --output plots/charge.png \
  --dataset 0 --value-transform logabs --log-floor 1e-5 \
  --isolevels 0.01 0.02 0.04 --no-symmetric-color
```

```bash
epirefine volume-slice --volume transferred/SPIN.vasp --output preview.png \
  --poly-atoms O2 O5 O8 O9 O11 O12 --plane-atoms Ru2 O2 O5 \
  --grid-points 320 --span 6.0 --dry-run
```

## `help-all`

Print this packaged reference. It works from a source checkout, PATH-based clone, or
normal Python installation and does not require scientific dependencies.

```bash
epirefine help-all
```

```bash
epirefine help-all | less
```

```bash
epirefine help-all > epirefine-command-reference.md
```

## External-tool and HPC notes

VASPKIT must be acquired under its own terms, configured independently (including its
own `~/.vaspkit` if needed), and acknowledged in publications that use it. EpiRefine
stores only its executable path and SHA-256. The VASPKIT extraction hook requires
CHGCAR, so the corresponding static calculation must use `LCHARG = .TRUE.` and retain
enough storage for the derived volumetric files.

On an HPC clone, add only EpiRefine's `bin` directory to PATH. Configure a cluster
VASPKIT path in that account's registry, preview extraction, then collect:

```bash
export PATH="$HOME/software/EpiRefine-HPC/bin:$PATH"
epirefine tool-config vaspkit --path /path/on/cluster/to/vaspkit
epirefine extract-volumetric --root static --products charge spin --dry-run
epirefine collect --root static --archive static.tar.gz --vaspkit-extract charge spin
```

The compatibility wrapper accepts the same collect options after its two paths:

```bash
hpc/collect_outcars.sh static static.tar.gz --vaspkit-extract charge spin
```

For guided interactive use, the separately installed `epirefine-tui` provides project
initialization, full workflow forms, artifact discovery, analysis, and guarded run
controls. It delegates to this CLI and is not required for any command documented
above. See the [TUI guide](../../docs/TUI.md).
