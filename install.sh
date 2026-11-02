#!/usr/bin/env bash
# Install every package in editable mode and link every skill into ~/.claude/skills.
set -euo pipefail
cd -- "$(dirname -- "$0")"
for p in packages/*/; do pip install -q -e "$p"; echo "installed $(basename $p)"; done
mkdir -p ~/.claude/skills
for s in skills/*/; do n=$(basename "$s"); ln -sfn "$PWD/skills/$n" ~/.claude/skills/"$n"; echo "skill $n -> ~/.claude/skills/$n"; done
