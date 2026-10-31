# pin-table-1030 rev3: scored-row SDK correction (data only, no rerun)

Corrects the recorded `@ai-sdk/anthropic` version on already-scored rows whose
binary bundles its own SDK (see #217 rev2 audit). These builds ignore the
installed `node_modules`; the request User-Agent comes from the bundled copy.

| study | PR | build(s) | scored cells | recorded (original_installed) | loaded_anthropic |
|---|---|---|---|---|---|
| H1 | 50272 | c10134729d | 8 groups / 42 rows | 3.0.71 | 3.0.111 (`var UQ="3.0.111"`) |
| H2 | 11731 | 0dc80df6fd (without) | 1 group / 90 rows | 2.0.77 | 2.0.58 (`var VERSION="2.0.58"`) |

Columns: `bundled=True`, `pin_source_class=bundled`, `loaded_anthropic` = embedded
version. The original values are kept unchanged in `original_installed`,
`original_actual_installed_mode`, `original_pin_rule`. Source rows: #214
`results/pin-table-1030/pin-table.csv`, #217 `rev2/pin-table.csv` (not modified).
Versions re-verified with the minified-bundle scanner from the loaded_anthropic code PR.
