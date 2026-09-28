#!/usr/bin/env bash
# Lightweight source-checkout install for machines without pip/build tooling.
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
bindir=${1:-"$(python3 -m site --user-base)/bin"}
mkdir -p "$bindir"
commands=(epirefine epirefine-tui)
for command in "${commands[@]}"; do
  target="$bindir/$command"
  source="$repo/bin/$command"
  if [[ -e "$target" || -L "$target" ]]; then
    current=$(readlink "$target" 2>/dev/null || true)
    if [[ "$current" == "$source" ]]; then
      continue
    fi
    echo "refusing existing command: $target" >&2
    echo "remove or rename it explicitly, then rerun this installer" >&2
    exit 2
  fi
done
for command in "${commands[@]}"; do
  target="$bindir/$command"
  source="$repo/bin/$command"
  if [[ -L "$target" ]]; then
    echo "already installed: $target -> $source"
  else
    ln -s "$source" "$target"
    echo "installed: $target -> $source"
  fi
done
echo "ensure $bindir is on PATH"
