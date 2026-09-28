# Expanse login-node smoke test

Date: 2026-09-28  
Environment: SDSC Expanse login node  
Python: 3.13  
EpiRefine-HPC tested revision: 0.2.0 (workflow core retained through 0.4.0)

This test used temporary `/tmp` storage on the login node. It did not access
Lustre, invoke VASP, or call `sbatch`. The temporary directory was removed after
the test.

## Relaxation scaffold

- One RuO2(001) fixture was strained from `(0%, 0%)` to `(+0.5%, -0.5%)`.
- The in-plane lattice changed from `(4.5000 A, 4.5000 A)` to
  `(4.5225 A, 4.4775 A)` as expected.
- Validation initially failed closed with one issue because POTCAR was absent.
- `hydrate` used a site-local Ru/O POTCAR kept outside the package. Its checksum
  was recorded in the temporary manifest but is intentionally omitted here.
- Validation then passed with one submission-ready run.
- Submission preview returned `would_submit`; execution remained false.
- The relaxation script contained 32 tasks, 16 GB, 3:30 walltime, and
  `mpivasp64s.rlxZ`.

## Static handoff

A synthetic normal-termination/ionic-convergence marker was used only to exercise
the handoff logic; it was not a VASP result. The static scaffold accepted one run,
rejected zero, copied the final geometry byte-for-byte, and passed validation.
Its submission preview also returned `would_submit`. The static script contained
32 tasks, 32 GB, 2:00 walltime, and ordinary `mpivasp64s`; the INCAR retained the
documented PBE/AFM, EDIFF=1E-7, ISMEAR=1, and SIGMA=0.20 settings.

## Transfer archive

The generated archive contained relative-path checksums for all six selected
files. Checksum verification passed, and inspection confirmed that POTCAR was not
present in the archive.

This establishes that the CLI, templates, path handling, POTCAR hydration,
manifest hashing, validation, submission preview, static handoff, and archive
exclusion work in the Expanse login environment. It is not evidence that VASP
itself converges for a scientific calculation.

## VASPKIT extraction extension

The optional VASPKIT hook was tested separately on the same Expanse login-node
environment using a site-local VASPKIT 1.5.1 executable and a copied 4.58 MB
spin-polarized RuO2 CHGCAR in isolated temporary storage. No VASP calculation or
Slurm job was run.

- `epirefine tool-config` registered the executable in a temporary registry and
  recorded its SHA-256; the machine-specific fingerprint is intentionally omitted.
- VASPKIT task 311 produced `CHARGE.vasp` (2,158,356 bytes), and task 312 produced
  `SPIN.vasp` (2,158,356 bytes).
- EpiRefine classified both tasks as extracted and recorded output hashes.
- A subsequent integrated `collect --vaspkit-extract charge spin` recognized both
  products as existing, did not overwrite them, and included the volumes plus
  `.epirefine-vaspkit.json` in its checksummed archive.
- The original CHGCAR and all POTCAR files remained excluded from the archive.
- The temporary package, executable copy, CHGCAR, derived volumes, registry, and
  archive were removed after verification.

This validates the real VASPKIT process boundary and the archive hook. It does not
validate every VASPKIT task or the physical interpretation of a particular density.
