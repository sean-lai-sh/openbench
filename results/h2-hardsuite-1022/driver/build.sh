#!/bin/bash
# Historical H2 build context. The image definition with pinned checker deps
# lives in the repo at thesis/ab/h2env. This script only forwards to it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
exec bash "$ROOT/thesis/ab/h2env/build.sh" "$@"
