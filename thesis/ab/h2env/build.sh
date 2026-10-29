#!/bin/bash
# Build the H2 cell image with checker deps baked in.
# Requires the local base image h1-env:1022. Tags h2-env:1022 unless a tag is given.
set -euo pipefail
cd "$(dirname "$0")"
TAG="${1:-h2-env:1022}"
docker build -f Dockerfile -t "${TAG}" .
