#!/usr/bin/env bash
set -euo pipefail
set +e
python3 - << 'PY'
import sys
import traceback

def verdict(code):
    if code == 0:
        print("OBENCH_VERDICT: pass")
    elif code == 1:
        print("OBENCH_VERDICT: fail")
    raise SystemExit(code)

def main():
    try:
        import config
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if getattr(config, "PORT", None) != 8417:
        print(f"FAIL: PORT={getattr(config, 'PORT', None)!r}", file=sys.stderr)
        return 1
    print("PORT is 8417")
    return 0

try:
    verdict(main())
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    raise SystemExit(2)
PY
status=$?
set -e
exit "$status"
