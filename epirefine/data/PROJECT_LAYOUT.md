# EpiRefine project layout

This project keeps human inputs, generated calculations, transferred results, and
editable execution templates separate.

```text
config.json                         adaptive thresholds, planes, system, VASP commands
inputs/
  structures/                       source POSCAR/CONTCAR/CIF files for matching/building
  kpoints/                          convergence-tested KPOINTS files
  markers/                          optional contour-marker CSV files
templates/
  relax.INCAR                       editable relaxation INCAR template
  static.INCAR                      editable static INCAR template
  relax.job.slurm                   editable relaxation Slurm template
  static.job.slurm                  editable static Slurm template
  KPOINTS                           placeholder/default mesh; replace after convergence tests
data/
  raw/accepted_geometries/          accepted POSCAR/CONTCAR trees used as scaffold sources
  raw/transfers/                    unpacked checksummed HPC result archives
  processed/                        immutable accumulated static-history CSV files
iterations/                         proposal, relaxation, and static directories by iteration
plots/                              generated contour/history/volumetric figures
provenance/                         tool status, mismatch, audit, and analysis reports
```

## Structures and geometries

Put reference bulk structures and manually supplied POSCAR/CIF files in
`inputs/structures/`. These are convenient project conventions rather than hidden
search paths: commands and TUI forms still record the explicit selected path.

For adaptive relaxation scaffolding, `--source-root` must contain the accepted
geometries named by the accumulated history. Keep those under
`data/raw/accepted_geometries/`, or retain unpacked collection archives under
`data/raw/transfers/` and point the form at the appropriate result tree.

For a static-only study, `scaffold-direct-static` uses the same source/history
contract but writes static inputs immediately. It preserves fractional coordinates
and c while scaling a/b. Keep its histories separate from relaxed-at-target histories;
the generated `geometry_protocol` field records the distinction.

## Editable VASP and scheduler templates

Edit the files in this project's `templates/` directory, not the package's master
copies. Supplying this project's `config.json` makes `scaffold-relax` and
`scaffold-direct-static`/`scaffold-static` use these editable templates automatically.

The scaffolder recognizes `{{SYSTEM}}`, `{{VASP_COMMAND}}`, and scheduler template
fields used by the packaged examples. Review all INCAR and Slurm settings for the
actual material, cluster, convergence tests, account, partition, resources, modules,
and executable before submission.

## KPOINTS and POTCAR

Store convergence-tested, redistributable KPOINTS files in `inputs/kpoints/` and pass
one explicitly while scaffolding or hydrating. The copied `templates/KPOINTS` is a
placeholder, not a universal converged mesh.

Do **not** place licensed POTCAR files in this project or a Git repository. Keep them
in a secure site-specific location on the HPC system and pass the path to
`epirefine hydrate --potcar ...`. POTCAR is hashed in manifests for validation but is
always excluded from collection archives.
