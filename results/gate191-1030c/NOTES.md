# #191 regate at 666223ec43 (checker flock + provenance fallbacks), 2026-10-30 ET

Cell: Opus (claude-opus-5-5) PR 4204, torch-tensor-parallelism, trial 1, both sides, --jobs 2, host networking.
Runner 666223ec4342839188da357661b141a10495d193 (cursor/checker-timeout-fix). Agent image h1-env:1022
(sha256:3ef8e823...b224). Checker venvs h2-checker-venvs:b43e88d1 (sha256:03af82dd...7997), stage reused
from gate191b (requirements unchanged). Original binaries. OBENCH_CHECKER_LOCK=/h2/checker.lock.
Pre-checks: venv preflight rc=0; spend self-test PASS ($0.3708). $5 stop not hit.

| side | verdict | checker_exit | t_checker_s | lock_wait_s | EADDRINUSE | cost |
|---|---|---|---|---|---|---|
| with | solved (13 passed) | 0 | 34.2 | 0.0 | no | $0.3098 |
| without | solved (13 passed) | 0 | 32.4 | 28.55 | no | $0.2885 |

Total spend $0.5982. Pass: both real verdicts < 600 s, no EADDRINUSE, no missing_fields, lock_wait_s present.
The without checker waited 28.6 s for the with checker's lock, so the checkers ran one after another.

Provenance caveat: probe_method=manifest means provider_loaded_version (2.0.0) was read from the
installed package manifest, not traced (h1-env:1022 has no strace and the binaries bundle no provider).
step8_gate's PROBE_METHODS is still (strace, embedded), so it still treats these rows as unproven.

audit/collision-audit.csv: torch-* checker rows from #196 (pi-vs-oc-180-1029), #135 (h2-deferred-26821-1024)
and H2 (h2-hardsuite-1022). Checker interval = [ended_et - t_checker_s, ended_et], overlap = same results set.
