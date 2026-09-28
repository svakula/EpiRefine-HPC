#!/bin/bash
# Example only: adapt account, partition, modules, ranks, memory, and walltime.
#SBATCH --job-name={{JOB_NAME}}
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --mem=32G
#SBATCH --time=02:00:00
set -euo pipefail
module load vasp
{{VASP_COMMAND}} > vasp.out 2>&1
