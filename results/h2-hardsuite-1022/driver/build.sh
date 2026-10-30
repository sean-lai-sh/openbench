#!/bin/bash
# The agent image is h1-env:1022 and is not rebuilt here.
# This forwards to the checker-venv artifact build (h2-checker-venvs).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
exec bash "$ROOT/thesis/ab/h2env/build.sh" "$@"
