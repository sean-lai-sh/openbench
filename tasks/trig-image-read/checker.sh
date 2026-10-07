#!/usr/bin/env bash
set -uo pipefail
python3 -c 'import config; assert config.PORT == 8417'
