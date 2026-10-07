#!/usr/bin/env bash
# `python3 -m unittest` with no arguments does not discover tests/ (Python 3.12
# exits 5, "NO TESTS RAN"). Discover the file the instruction names.
set -uo pipefail
python3 -m unittest discover -s tests -p 'test_*.py'
