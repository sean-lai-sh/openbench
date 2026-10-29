# Pi vs OpenCode gate cells, main 4a5111d9 (2026-10-29, VM thesis-h1-cpu)

Code: main 4a5111d9 (#183 proxy cost/--max-spend, #184 docker /app + in-image checker), shipped as an incremental git bundle, detached in ~/ob-pr134.
Image h1-env:1027-strace. OBENCH_ADC_METADATA=1. Pi pin d0aa218c, Node 22.19.0. OpenCode sha ba54cee5, Node 20.19.2. Same commands as the 1028c smoke (gate1029.sh). Batch NOT launched (on hold per PM).

## #184 docker test on VM (test_docker_scoring.unittest.out)
`python3 -m unittest -v obench.tests.test_docker_scoring`: Ran 10 tests in 110.6s, OK, 0 skipped.
test_reference_solution_passes_inside_task_image ... ok; test_known_bad_answer_fails ... ok (real docker, 110 s).
(test_docker_scoring.out: first attempt via pytest failed, pytest isn't installed in ~/venv.)

## Gate cells
| | Pi 6cf27fde8edd0132 | OpenCode 41adfe799c38d27a |
|---|---|---|
| network_mode | bridge | bridge |
| egress | api.anthropic.com blocked (sinkhole) | same |
| proxy-reached | reached=yes calls=2 | reached=yes calls=4 |
| thinking (default) | adaptive (Pi providerThinkingLevel=medium) | none sent |
| upstream_model (ledger, every request) | claude-sonnet-5-5 | claude-sonnet-5-5 (harness label claude-opus-5-5; proxy maps to vertex_model) |
| ledger in/out/cache-write/cache-read | 6 / 2193 / 7230 / 0 | 12 / 3286 / 49776 / 0 |
| proxy_cost_usd | 0.0600255 | 0.235986 |
| output kept in /app | yes | yes |
| checker | in-image, checker_defect=false, exit 1 | same |
| score | 0 (wrong_answer) | 0 (wrong_answer) |

Both wrong_answers are genuine task failures, not harness bugs: both agents wrote a working polyglot (self-tested, both compilers) but left
the compiled binaries `main` and `cmain` in /app/polyglot; the task test asserts the directory contains only main.rs.

## Ledger vs harness trace
- Pi: 2 ledger requests (both status 200) = 2 assistant messages in the trace. No retries/errors occurred, so retry-dropping can't be tested from this cell.
- OpenCode: 4 ledger requests (all 200) vs 3 step_finish in the trace. The untraced one is the first request (cache_write 1033, out 20), the small side call OpenCode makes before the main loop (title-style). No retries/errors occurred.
- OpenCode's own step costs sum to 0.309067 (its internal price table), vs proxy_cost_usd 0.235986 for the 3 traced+1 untraced calls; scored cost uses the proxy.

Spend: $0.296 total.
