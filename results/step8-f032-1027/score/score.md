# F03-2 step-8 score (sean-lai-sh/openbench #172, head 50d64edf = main 41877c92 data, identical)
Computed directly from cell JSONs (score.py), not the summarize tool. Pass = success && no missing fields other than probe_method/provider_loaded_version (strace_on=false).

| PR | with | without | diff | Wilson95 with | Wilson95 without | Newcombe95 diff | Fisher p | Holm p | $/cell w / wo | wall s w / wo |
|---|---|---|---|---|---|---|---|---|---|---|
| 3251 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | -.114..+.114 | 1 | 1 | .177/.175 | 21.0/20.5 |
| 3302 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | ±.114 | 1 | 1 | .047/.049 | 7.7/7.8 |
| 3381 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | ±.114 | 1 | 1 | .044/.047 | 7.7/7.8 |
| 3390 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | ±.114 | 1 | 1 | .105/.098 | 12.3/12.2 |
| 3402 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | ±.114 | 1 | 1 | .053/.051 | 9.9/9.8 |
| 3424 | 0/30 | 0/30 | 0 | 0-.114 | 0-.114 | ±.114 | 1 | 1 | .112/.116 | 18.4/19.1 |
| 3433 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | ±.114 | 1 | 1 | .052/.048 | 8.7/8.7 |
| 3449 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | ±.114 | 1 | 1 | .061/.055 | 13.0/12.0 |
| 3481 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | ±.114 | 1 | 1 | .048/.051 | 11.1/11.6 |
| 3507 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | ±.114 | 1 | 1 | .042/.045 | 8.5/8.7 |
| 3546 | 30/30 | 30/30 | 0 | .886-1 | .886-1 | ±.114 | 1 | 1 | .173/.171 | 23.0/23.2 |

No PR significant (all Holm p = 1). Ceiling/floor everywhere: screen can only exclude effects > ~11 pts.

## Checks
- 22/22 sides complete, incomplete={}, untagged_rerun_cells=[], excluded_traced=[]; complete.json cell lists == files on disk.
- 660 scored cells, all strace_on=false, gate_cell=false, rerun=0, route=on:provider-options on every cell; no off_route (route-scored.json off_route={}, rerun=[]). All 11 pairs route-matched.
- No missing fields beyond the two known false flags.
- build_channel_source: every side resolves via binary sha (21 shas: 19 inferred, 2 stamp). Stamp sides: 3481/with (c1ada302), 3481/without (51e4c9fc) and **3546/with (same 51e4c9fc binary as 3481/without)**, so "stamp" is not 3481-only as RUN-NOTES says.
- Spend: scored $54.50 + gate $2.03 + prior $2.08 = $58.61 (matches spend.log 58.45 last tick + final), under $70.
- 03:44 projection halt: old complete.*0345.json had 3251 with/without at 12/30; final has 30/30 each, 30 unique trials per side, 12 per side started 03:42-03:43 (pre-halt) and kept, none rerun/duplicated/dropped. Consistent with RUN-NOTES.
- Model: cells say model=claude-opus-5-5 (OpenCode alias) with upstream_model=claude-sonnet-5-5 on all 660; the 3481/with "model not listed" issue is not visible (3481/with 30/30 solved, same model fields as others).
- 3424: both sides 0/30 wrong_answer (task trig-plan-subagent): looks like a task/checker floor; check before reading it as a PR result.
- Secret grep (AKIA/ghp_/sk-ant/private keys): none.
