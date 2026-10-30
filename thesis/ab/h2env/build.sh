#!/bin/bash
# Build the checker-venv artifact. Does not modify h1-env:1022 and does not
# tag an image the agent runs in. Default tag: h2-checker-venvs:latest.
set -euo pipefail
cd "$(dirname "$0")"
TAG="${1:-h2-checker-venvs:latest}"
case "${TAG}" in
  h1-env:*|h2-env:*|h1-env|h2-env)
    echo "refusing to tag the checker artifact as the agent image (${TAG})" >&2
    exit 2
    ;;
esac
docker build -f Dockerfile -t "${TAG}" .
