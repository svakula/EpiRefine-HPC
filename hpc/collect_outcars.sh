#!/usr/bin/env bash
# Compatibility wrapper; the same EpiRefine CLI is used locally and on HPC.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
if command -v epirefine >/dev/null 2>&1; then cli=(epirefine); else cli=("$here/bin/epirefine"); fi
dry=()
if [[ ${1:-} == --dry-run ]]; then dry=(--dry-run); shift; fi
[[ $# -ge 2 ]] || { echo "usage: $0 [--dry-run] RUN_ROOT ARCHIVE.tar.gz [collect options...]" >&2; exit 2; }
root=$1; archive=$2; shift 2
exec "${cli[@]}" collect --root "$root" --archive "$archive" "${dry[@]}" "$@"
