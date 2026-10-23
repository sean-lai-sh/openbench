#!/bin/bash
set -euo pipefail
cd /tmp
for f in /opt/h2-checkers/*.sh; do
  # take the uvx block, swap the final pytest invocation for `pytest --version`
  cmd=$(sed -n '/^uvx/,/[^\\]$/p' "$f" | tr -d '\\\n' | sed -E 's/ pytest --ctrf.*$/ pytest --version/')
  vars=$(grep -E '^(export )?[A-Z_]+=' "$f" || true); eval "$vars"
  echo "== $f: $cmd"; eval "$cmd"
done
