# RuO2 PBE/AFM Expanse example

This profile records the settings used by the originating RuO2 adaptive-strain
study. It is an example, not a convergence certificate.

After `epirefine init PROJECT`, copy `config.json`, `relax.INCAR`, and
`static.INCAR` from this directory over the corresponding project files. Keep
the separate packaged relaxation/static Slurm templates or edit them for the
current Expanse account and modules.

The relaxation command is the local `mpivasp64s.rlxZ` build that preserves the
in-plane epitaxial lattice and relaxes z; the static command is ordinary
`mpivasp64s`. Neither executable—especially the custom `rlxZ` build—is supplied by
this repository; users must provide and validate their own site-compatible binaries.
Relaxation uses PBE, AFM `2 -2 2 -2 8*0`, ISMEAR=1,
SIGMA=0.20, EDIFF=1E-6, and EDIFFG=1E-4. Static calculations use EDIFF=1E-7.
The packaged example Slurm resources are 32 cores/16 GB/3:30 for relaxations
and 32 cores/32 GB/2:00 for statics.

The active plane list is deliberately editable. This example lists 001 and 100
because those were the continuing refinement planes; add 110 for an earlier
stage or remove a plane once its predeclared stopping criterion is met. Reuse
the accepted source run's KPOINTS when meshes differ by orientation.
