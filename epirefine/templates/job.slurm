#!/bin/bash
# Adapt account, partition, modules, ranks, memory, and walltime to your site.
#SBATCH --job-name={{JOB_NAME}}
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --time=24:00:00
set -euo pipefail
module load vasp
{{VASP_COMMAND}} > vasp.out 2>&1
