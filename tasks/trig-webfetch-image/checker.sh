#!/usr/bin/env bash
set -uo pipefail
python3 -c 'from pathlib import Path; text = Path("answer.txt").read_text(encoding="utf-8").strip().lower().strip("."); assert text == "red"'
