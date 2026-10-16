#!/usr/bin/env bash
# Selftest for the 16 trig-omp-* tasks. No model calls.
#   fail: checker on the untouched workspace  -> exit 1 and "OBENCH_VERDICT: fail"
#   pass: checker on workspace + solution/    -> exit 0 and "OBENCH_VERDICT: pass"
#   echo: in both cases, exactly one OBENCH_VERDICT line, matching the exit code
# Usage: selftest.sh [tasks_dir]   (needs pytest on PATH's python3 for the 10 main tasks)
set -uo pipefail
TASKS="${1:-$(cd "$(dirname "$0")" && pwd)/tasks}"
PY_VENV="$(cd "$(dirname "$0")/.." && pwd)/.venv-selftest/bin"
[ -x "$PY_VENV/python3" ] && export PATH="$PY_VENV:$PATH"
ok=0; bad=0
run() { # task_dir mode -> sets rc, vline, nlines
  local t="$1" mode="$2" tmp; tmp="$(mktemp -d)"
  cp -a "$t/workspace/." "$tmp/"
  [ "$mode" = pass ] && cp -a "$t/solution/." "$tmp/"
  out="$(cd "$tmp" && TASK_DIR="$t" bash "$t/checker.sh" 2>&1)"; rc=$?
  nlines=$(grep -c '^OBENCH_VERDICT: ' <<<"$out"); vline=$(grep '^OBENCH_VERDICT: ' <<<"$out" | tail -1)
  rm -rf "$tmp"
}
report() { if [ "$2" = OK ]; then ok=$((ok+1)); else bad=$((bad+1)); fi; printf '%-26s %-5s %-3s %s\n' "$1" "$3" "$2" "$4"; }
for t in "$TASKS"/trig-omp-*/; do
  t="${t%/}"; n="$(basename "$t")"
  run "$t" fail; f_rc=$rc; f_v=$vline; f_n=$nlines
  [ $f_rc -eq 1 ] && [ "$f_v" = "OBENCH_VERDICT: fail" ] && report "$n" OK fail "rc=1" || report "$n" BAD fail "rc=$f_rc '$f_v'"
  run "$t" pass; p_rc=$rc; p_v=$vline; p_n=$nlines
  [ $p_rc -eq 0 ] && [ "$p_v" = "OBENCH_VERDICT: pass" ] && report "$n" OK pass "rc=0" || report "$n" BAD pass "rc=$p_rc '$p_v'"
  e=OK
  for pair in "$f_rc|$f_v|$f_n" "$p_rc|$p_v|$p_n"; do
    IFS='|' read -r r v c <<<"$pair"
    want=$([ "$r" = 0 ] && echo "OBENCH_VERDICT: pass" || echo "OBENCH_VERDICT: fail")
    [ "$c" = 1 ] && [ "$v" = "$want" ] || e=BAD
  done
  report "$n" $e echo "verdict line matches exit code (fail rc=$f_rc, pass rc=$p_rc)"
done
echo "TOTAL: $ok ok, $bad bad"
[ $bad -eq 0 ]
