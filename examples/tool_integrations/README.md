# Tool integration examples

## Match a film to an epitaxial substrate

Keep the matching report next to the EpiRefine run so the strain convention
and orientation can be audited later:

```bash
epirefine interface-match substrate.cif film.vasp \
  --substrate-plane '(0001)' --film-plane '(100)' \
  --substrate-swap-axes --film-swap-axes \
  --out match.json --marker-out marker.csv \
  --marker-plane 100 --marker-label 'substrate(0001)'
```

Copy the selected, exported interface POSCAR into the local scaffold's input
directory. The adaptive sampler then refines the observable over the chosen
epitaxial strain coordinates; it does not replace the structural match search.

## Inspect local distortions after a run

Use the polyhedron slice launcher with a VASP volumetric or local-geometry file
after transferring results from the cluster:

```bash
epirefine volume-slice --volume SPIN.vasp --output spin_slice.png \
  --report spin_slice.json
```

For a paper-quality report, retain `match.json`, the EpiRefine manifest, the
OUTCAR hash manifest, and the viewer input file together.
The compatibility launchers in `tools/` remain available for the original GUIs;
new scripts should use the stable CLI or `epirefine.api` described in the
[API guide](../../docs/API.md).
