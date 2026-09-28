# Companion analysis tools

The supported public interface is now the unified `epirefine` CLI and
`epirefine.api` Python module:

```bash
epirefine tool-status
epirefine interface-match substrate.cif film.vasp --out match.json
epirefine hstruct -- domain-search substrate.cif film.vasp --json
epirefine volume-slice --volume SPIN.vasp --output slice.png
```

See [`../docs/API.md`](../docs/API.md) for the typed API and full examples. The
small launchers below remain compatibility conveniences for the original interactive
tools; they do not copy or change their implementations:

```bash
python tools/hstructpy_adapter.py analyze substrate.cif film.vasp \
  --substrate-plane '(0001)' --top-plane '(100)' --json
python tools/hstructpy_adapter.py gui
python tools/polyhedron_slice_adapter.py
```

`hstructpy_adapter.py` locates `grandStrainComparison/hstructpy` in this
repository. If the suite is moved without the parent checkout, set
`HSTRUCTPY_ROOT=/path/to/hstructpy` (the directory containing `src/hstructpy`).
Its CLI and GUI are otherwise unchanged. Use the main README for detailed
surface construction, domain matching, strain definitions, and export options.

The contour plotting and Delaunay refinement utilities are part of the local
pipeline under `bin/` and `hpc/`; this directory only hosts complementary
heterostructure and volumetric inspection entry points. The polyhedron viewer
is likewise located in the original `spindensityexploration/BondStrainPY`
tree, preserving provenance and avoiding a second implementation.

Optional dependencies are tool-specific: hstructpy requires Python >=3.10,
ASE, NumPy, and Matplotlib; its GUI additionally needs a working Tk backend.
The polyhedron viewer uses the dependencies documented by its original script
(typically NumPy/Matplotlib and VASP volumetric-file parsing support). A
VASP installation is not needed for these local viewers.
