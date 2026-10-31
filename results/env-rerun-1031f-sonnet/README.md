# env-rerun-1031f-sonnet — Sonnet 3052 completion rerun (2026-10-31)

Completes the Sonnet 3052 arm from #229 (env-rerun-1031c, 130/180). Data only, do not merge without Researcher review.

## Run
- 52 cells (`cells-1031f.txt`): the 50 cells with no row + the 2 unproven regex-chess/2 rows (with, without; ruling c). Source list `results/env-rerun-1031/sonnet-3052-missing.csv` on #229.
- VM thesis-h1-cpu, code 461c6fa0 (main, #228 spec-file driver), image h2-env:1022@sha256:72c59033…69ff, pin 2.0.25 (rev2, pin_table_check ok), PFX e1031g, per-VM STOPAT $15.
- 16:52:25 → 17:29:44 EDT, container exit 0. No local or central stop fired.
- All 52 rows: loaded_anthropic 2.0.25, load_proof pass. ledgermap: 52 ledgers ↔ 52 rows, 0 orphans (`box/ledgermap.txt`).

## Results (rows.csv)
| side | solved | wrong_answer | hang | infra | $ |
|---|---|---|---|---|---|
| with | 8 | 15 | 0 | 3 | 4.8154 |
| without | 10 | 15 | 1 | 0 | 5.2010 |
| **total** | 18 | 30 | 1 | 3 | **10.0164** |

- **3 infra = signature 400s, with arm:** sam-cell-seg/9 (ledger ef2f3800), video-processing/9 (b995d7ff), video-processing/10 (11224c42). Each matched ledger contains the exact "Invalid `signature` in `thinking` block" 400 → `pr_harness_trace` (pr3052-msgv2.diff) under ruling (a). No other ledger contains it.
- **1 hang:** without/regex-chess/8, watchdog `no_progress idle_s=300.0` (same 300 s on both arms, ruling b).
- regex-chess/2 reruns: with wrong_answer ($0.4092), without wrong_answer ($0.4093). Ledger-backed replacements for the unproven #229 originals.

## Sonnet 3052 arm, combined (#229 env-rerun-1031c counted 128 + these 52 = 180; infra excluded from denominator, hang = failure)
| scope | with | without |
|---|---|---|
| all tasks | 30/77 = 0.390 (47 WA, 13 infra) | 32/90 = 0.356 (57 WA, 1 hang) |
| excl. regex-chess | 28/67 = 0.418 | 30/80 = 0.375 |

## Flag
`model`/`requested_model` = claude-opus-5-5 while `upstream_model`/`protocol_model` = claude-sonnet-5-5 on all 52 rows, and transcript names say opus. The #229 env-rerun-1031c Sonnet rows have the identical pattern, so this is consistent with the arm being completed. The served model per proxy is Sonnet, and the cost per cell is Sonnet-scale. Needs a Researcher look at the label source.

## Spend / central stop
- Run $10.0164. Central monitor v2 (`box/central-f.sh`, polls RUNNING VMs only, 15 s ssh ConnectTimeout, keeps a stopped VM's last value) ran with PRIOR $105.62 and ended at cumulative **$115.64** / $297 (`box/central-f.log`).
- PRIOR reconciliation (in #229 README): $12.30 pre-10/31 + $91.50 (#229 folders) + $1.81 (VM3 first-wave 13331, not copied) = $105.61.

## Files
`run/` is the run folder minus transcripts. The transcripts are listed in `MANIFEST-transcripts.txt` (`bytes path sha256`, 1733 files). The full backup including transcripts is `/workspace/h2-backup/env-rerun-1031f-sonnet-full.tgz` (sha256 27457190e4cd2c90c36ecf8a213f69353b5630ff2a82dc3e34ba498fc5e935a6) on the box.
