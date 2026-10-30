# ProviderPinMismatch / NameError audit (2026-10-30)

Bug: `obench/adapters/opencode.py` caught `except ProviderPinMismatch` by a bare
name that was never imported (added in #143, c25856a78b, 2026-10-26). Any
adapter exception that reached that `except` chain raised NameError.

Method: on thesis-h1-cpu, `sudo grep -rlE` over every file of each batch dir
(results, cell json/jsonl, driver logs, transcripts) for `ProviderPinMismatch`,
`provider_pin_mismatch` and `NameError: name 'ProviderPinMismatch'`. Every other
`NameError` hit was listed and checked by hand.

| batch | dir | runner_commit | has #143 code | files | harness NameError | ProviderPinMismatch | cells |
|---|---|---|---|---|---|---|---|
| pi-vs-oc-180-1029 (#196) | ~/pvo180 | e507e38c | yes | 1,446 | 0 | 0 | none |
| h2-hardsuite-1022 | ~/h2/h2-hardsuite-1022 | 980e71b6 | no | 30,900 | 0 | 0 | none |
| h2-deferred | ~/h2/h2-deferred-1023 | e2ac6b75 | no | 48,152 | 0 | 0 | none |
| h2-deferred-26821-1024 (#135) | ~/h2/h2-deferred-26821-1024 | e2ac6b75 | no | 1,992 | 0 | 0 | none |

The only NameErrors found are in the agents' own scripts in transcripts
(`__file__`, `sol`, `SKY_FRAC`, `TRACK_BOTTOM_Y`, `a`, `idx`, `p`, `ry0`), which
are agent work, not harness errors: 6 files in h2-hardsuite-1022, 29 in h2-deferred.
The three H2 batches ran on commits from before #143, so they could not hit
the bug. #196 ran with the bug, but no exception reached that handler.

`provider-pin-nameerror-1030.csv` has the header only: no cells hit, so no
pinned or unpinned cells are added to the rerun plan.
