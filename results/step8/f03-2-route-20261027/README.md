# F03-2 route fix + egress backstop (PR #166 round 3, 2026-10-27)

No model calls. Readiness runs use the local stub; the egress block was active for all of them.

## Route fix
* `thesis/ab/compat.py`: both routes now set the base URL. Provider-options route: config
  `options.baseURL` + `ANTHROPIC_BASE_URL`. Env route (builds that reject the `api` key): env var
  + `options.baseURL` without `api` when the build lists the model with it (third `models` probe),
  else env-only (the egress block and route check cover that case). `proxy.route` records how.
* `obench/adapters/opencode.py`: always exports `ANTHROPIC_BASE_URL` when proxied.
* `thesis/ab/route.py`: `route` = `on:<how>` if >=1 request reached the expected endpoint
  (per-cell proxy ledger in run_ab; the stub in readiness), else `off:<how>`. Missing = off.
* `run_ab.apply_cell_meter` writes `route` on every scored and gate cell; `step8_stub_ready` adds the column.
* `step8_gate.py`: an off-route gate cell fails the side (rerun as infra); `--route RUN_DIR`
  lists off-route cells (label `infra:off_route`, not scored, rerun), halts a side with >2,
  halts the batch with >2 halted sides. The launcher runs it during monitoring and after the gate and scored phases.

## Egress verification (r3/egress.txt, times UTC)
| step | host | host by IP | container |
|---|---|---|---|
| before apply | reached (http 401, no key, no spend) | - | blocked (sinkhole) |
| after apply | blocked (connect refused) | blocked | blocked |
| after remove | reached (401) | - | blocked |
Rules: 160.79.104.10/32 and 2607:6bc0::10/128 REJECT in OUTPUT with tag obench-s8-egress. 0 left after remove.

## Readiness with route column (egress block on)
| run | side | ready | route | stub reqs | probe | loaded | pin |
|---|---|---|---|---|---|---|---|
| r3-3251-1 | 3251/without | True | on:provider-options | 2 | strace | 2.0.0 | 2.0.0 |
| r3-3251-1 | 3251/with | True | on:provider-options | 2 | strace | 2.0.0 | 2.0.0 |
| r3-3251-2 | 3251/without | True | on:provider-options | 2 | strace | 2.0.0 | 2.0.0 |
| r3-3251-2 | 3251/with | True | on:provider-options | 2 | strace | 2.0.0 | 2.0.0 |
| r3-3251-3 | 3251/without | True | on:provider-options | 2 | strace | 2.0.0 | 2.0.0 |
| r3-3251-3 | 3251/with | True | on:provider-options | 2 | strace | 2.0.0 | 2.0.0 |
| r3-c0dc | ctl-0dc80df6/rebuild | True | on:provider-options | 2 | embedded | 2.0.58 | 2.0.77 |
| r3-c0dc | ctl-0dc80df6/original | True | on:provider-options | 2 | embedded | 2.0.58 | 2.0.77 |
The control passes on rebuild == original (both 2.0.58) plus request match, as ruled in round 2. Its manifest pin is 2.0.77.
The flip did not recur in these 3 runs. If it does, it now fails closed: the request is refused by the host rule, and the cell is `off:` and rerun.
