# env-rerun-1031 — environment-rerun data (2026-10-31)

Data only. Nothing here was rerun to make this PR. All counts and dollar figures are measured from the committed row JSONs. Spend is the sum of row `requests_cost_usd`. Times are EDT unless marked UTC.

## Where things are
- `vm1/` holds thesis-h1-cpu (`~/h2/`) data: env-rerun-1031-aborted-start, env-rerun-1031b, env-rerun-1031c, env-rerun-1031d, env-rerun-1031d-argfail, plus the driver/guard scripts, `cells-1031d.txt` and the specs.
- `vm2/` holds thesis-h1-cpu-2 data: cells-rerun-1031, cells-rerun-1031c, cells-smoke-1031d, cells-rerun-1031e.
- `vm3/` holds thesis-h1-cpu-3 data: cells-rerun-1031c (13331).
- `box/` has the box-side monitor and analysis scripts and the central $297 stop logs. `box/analyze.py` regenerates the CSVs below.
- Transcripts and agent workspaces are **not committed**. Each `vmN/MANIFEST-transcripts.txt` lists them as `bytes path sha256`:
  - VM1: 11,525 files, 1,107,162,732 bytes. The largest is 381,850,076 bytes.
  - VM2: 451 files.
  - VM3: 140 files.
- Box backups are in `/workspace/h2-backup/env-rerun-1031-vm{1-full-incl-transcripts,2,3}.tgz`. Their sha256 values are in the manifest headers. No other file is over 50 MB.

## CSVs
| file | what it is |
|---|---|
| `rows-all.csv` | All 340 rows, one line per row JSON, with run, run_status, outcome, env_cause, cost, wall time, timeouts and loaded_anthropic. |
| `failure_basis.csv` | `failure_basis=pr_harness_trace` on the 24 listed rows, plus 5 more (see below), plus the 5140 infra row. |
| `ledger_match.csv` | Rows matched to their proxy ledger with `ledger_match_basis=token_cache_mtime`, used where the token fingerprint was ambiguous. |
| `load_proof_backfill.csv` | The `load_proof_basis` backfill (#227). It is an overlay; raw row JSONs are unchanged. |
| `hangs.csv`, `timeouts.csv`, `infra.csv` | The sections below. |
| `sonnet-3052-missing.csv` | The 50 Sonnet 3052 cells that have no row (see "Sonnet 3052 arm incomplete"). |
| `pr3052-msgv2.diff` | Evidence for pr_harness_trace (`packages/opencode/src/session/message-v2.ts`). |

## Opus 3052 arm: 180 rows, and how they reconcile with the 171-cell list
- **env-rerun-1031c, opus: 9 rows**, the trial-1 cells written before the pair-cap guard stopped e1031c-opus at 13:45:59 (code 431a1952).
  - with: dna-insert, filter-js-from-html, model-extraction-relu-logits, polyglot-rust-c
  - without: dna-insert, filter-js-from-html, model-extraction-relu-logits, polyglot-rust-c, sam-cell-seg
  - Outcomes: 3 solved, 6 wrong_answer. Spend $3.0211.
- **env-rerun-1031d, opus: 171 rows.**
  - `vm1/cells-1031d.txt` lists exactly 171 cells, and they are exactly the 171 rows.
  - Run details: 13:57:00 → 16:07:25, exit 0. Code bfa88e4c, image h2-env:1022@sha256:72c59033…69ff, pin 2.0.25 (rev2), stop_at $270.
  - Outcomes: 62 solved, 77 wrong_answer, 20 hang, 9 infra, 3 timeout. Spend $59.6586, maxpair $1.8436.
  - All 171 rows have loaded_anthropic 2.0.25. ledgermap gives 171 unique fingerprint matches, with 0 orphans and 0 ambiguous.
- The two sets are disjoint, and 9 + 171 = 180, which is 9 tasks × 2 sides × 10 trials.
- **Opus 3052 total: 65 solved, 83 wrong_answer, 20 hang, 9 infra, 3 timeout. Spend $62.68.**

## Aborted cells / runs (kept, not counted)
- **env-rerun-1031c, 4 opus in-flight cells** (`ABORTED-paircap.txt`): without/torch-pipeline-parallelism/1, with/sam-cell-seg/1, with/regex-chess/1, without/regex-chess/1.
  - They were killed at 13:45:59 (exit 137) when the pair-cap guard was wrongly applied. No rows were written.
  - All 4 are inside the 171 and were rerun in env-rerun-1031d.
  - Their 4 opus proxy ledgers are orphans with no row: 88ece50d, 9a3ea7e6, a86e1b36, b4b3f99e. The ledger totals carry tokens but no $ figure, so they are not in the spend sums.
- **The $1.60 pair note.** The pair cap was gates-only (Researcher 13:49). `opus/3052|filter-js-from-html|1` at **$1.6033** is VALID and counts (`vm1/env-rerun-1031c/paircap.NOTE`).
- **env-rerun-1031-aborted-start:** 0 rows, $0. Stopped on "STOP disk 13G".
- **env-rerun-1031b:** 13 rows, $2.1914. Opus has 1 solved and 4 wrong_answer; Sonnet has 3 solved and 5 wrong_answer.
  - It was aborted because rows lacked vm_name/instance_id (attach_cell_meta was fixed in 431a1952).
  - Not counted.
- **env-rerun-1031d-argfail:** 0 rows, $0. This was an earlier launch with the cell list passed inline; the container e1031e-opus exited 1 at 13:56. It was relaunched as env-rerun-1031d.
- **VM2 cells-rerun-1031 (13090):** 4 infra rows, $1.2297. Code e1ea72f0.
  - ABORTED-wrong-pin: the driver set pin 2.0.25, but the 13090 pin is 2.0.58. Not counted.
  - The ABORTED note says "8 infra rows, $3.04". Only 4 rows / $1.2297 are in this folder, and the committed figure is the measured one. The note's other rows are not in any copied folder.
- **VM2 cells-smoke-1031d attempt 1:** name collision, $0.
- **VM2 cells-rerun-1031e attempt 1:** launched only the first cell line, $0.

## Hangs (own section, separate from infra) — 20 rows, env-rerun-1031d opus
- These are **not 2400 s timeouts.** Every hang row was ended by the harness no-progress watchdog: `failure_reason = openbench-infra:no_progress idle_s=300.x`.
  - Wall times are 368–573 s, and the 2400 s `timeout_s` was never reached.
  - Hang spend is $11.7187.
- 19 rows are regex-chess: with 1–10, and without 1–8 and 10.
- 1 row is with/model-extraction-relu-logits/2. It also hit the 600 s checker timeout (env_cause=checker_timeout).
- No Sonnet run has hang rows.

## Checker timeouts — 3 rows, env-rerun-1031d opus
- These are without/model-extraction-relu-logits/7, 8 and 9, with outcome `timeout` and env_cause=checker_timeout.
- The checker ran 600 s; the agent phase took 57–107 s. Spend is $0.7608.

## Infra rows (failure_basis)
- **pr_harness_trace, 29 rows.** These are Invalid `signature` 400s on the with arm, traced to PR 3052's message-v2 change (`pr3052-msgv2.diff`).
  - The 24 listed rows:
    - env-rerun-1031c sonnet (VM1), 10 rows: sam-cell-seg 3, 5, 6, 7 and video-processing 1, 2, 3, 4, 6, 7.
    - env-rerun-1031d opus, 4 rows: video-processing 2, 4, 5 and sam-cell-seg 1.
    - h2-hardsuite-1022 opus, 7 rows: video-processing 2, 3, 5, 6, 9, 10 and sam-cell-seg 3.
    - h2-hardsuite-1022 sonnet, 3 rows: video-processing 4, 8 and sam-cell-seg 8.
  - **Plus 5 more** env-rerun-1031d opus rows written after the list was drafted: with/video-processing 6, 7, 8, 9 and 10. They have the same signature 400 and are marked "pending Researcher confirm" in `failure_basis.csv`.
  - So all 9 env-rerun-1031d infra rows carry the basis.
- **5140 infra row:** h2-hardsuite-1022/deferred-opus-attempt1, opus 5140 without/filter-js-from-html/1. It is infra_uncounted, signature_400_both_arms, and should be rerun with the 5140 group after its gate passes (not run).
- **VM2 cells-rerun-1031c (13090), 4 infra rows:** $1.8284, code bfa88e4c. These cells were redone in cells-smoke-1031d (1 solved, $0.4374) and cells-rerun-1031e (4 solved, $1.3112).

## ledger_match_basis=token_cache_mtime
This basis is used where the token fingerprint alone matched more than one ledger. Rows per run:

| run | rows |
|---|---|
| VM3 cells-rerun-1031c 13331 | 4 |
| VM2 cells-rerun-1031 | 4 |
| VM2 cells-rerun-1031c | 4 |
| VM2 cells-smoke-1031d | 1 |
| VM2 cells-rerun-1031e | 4 |
| VM1 env-rerun-1031c sonnet | 10 |

All other rows match their ledger by unique fingerprint.

## load_proof_basis backfills (#227)
- The rule: backfill `load_proof_basis=user_agent` only where every request in the row's matched ledger carries a UA-derived `loaded_anthropic`. Pass iff UA == the rev2 pin (3052→2.0.25; 13090/13331→2.0.58). Mixed versions fail.
- Results:
  - 338 rows backfilled, all pass.
  - The 4 VM2 cells-rerun-1031 rows are also UA 2.0.58 == the 13090 pin. They stay infra and not counted because the driver's pin env was wrong.
  - 2 rows are not backfilled: Sonnet env-rerun-1031c with/regex-chess/2 and without/regex-chess/2. Neither has a matching ledger.
- Raw row JSONs still show load_proof_basis=None.

## 13090 deviation
- Applies to cells-smoke-1031d and cells-rerun-1031e (`DEVIATION.txt`).
- The reference lockfile was taken from the commit (`git worktree add --detach` from the existing mirror at 6b4d617d/e3471526; bun.lock a888d58a…), because the 13090 source rows have none.
- Researcher OK 2026-10-31 14:46 EDT.

## Sonnet 3052 arm incomplete — 130 / 180 rows
- env-rerun-1031c sonnet has 44 solved, 76 wrong_answer, 10 infra. Spend $20.474.
- The run was SIGSTOPped at 17:49:57 UTC and SIGCONTed at 17:54:42 UTC (`pause.log`).
- The worker pool then died: `sonnet/run.log` shows KeyError '/mp-…' and `concurrent.futures.process.BrokenProcessPool`.
- **50 cells have no row** (`sonnet-3052-missing.csv`, mostly trials 8–10). They were not rerun. That needs a separate go.
- 7 Sonnet orphan ledgers exist for in-flight cells.

## Spend (measured, row sums)
| run | rows | $ | counted |
|---|---|---|---|
| VM1 env-rerun-1031b | 13 | 2.1914 | no (aborted) |
| VM1 env-rerun-1031c (sonnet 130 + opus 9) | 139 | 23.4951 | yes |
| VM1 env-rerun-1031d (opus) | 171 | 59.6586 | yes |
| VM2 cells-rerun-1031 | 4 | 1.2297 | no (wrong pin) |
| VM2 cells-rerun-1031c | 4 | 1.8284 | yes (infra rows) |
| VM2 cells-smoke-1031d | 1 | 0.4374 | yes |
| VM2 cells-rerun-1031e | 4 | 1.3112 | yes |
| VM3 cells-rerun-1031c (opus 3 + sonnet 1, 13331) | 4 | 1.3505 | yes |
| **total** | **340** | **91.5029** | counted 323 rows / 88.0818 |

The central $297 monitor (`box/central4.log`) last read cumulative $96.72 including PRIOR, using its own pair_spend accounting.
