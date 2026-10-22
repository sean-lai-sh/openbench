# PR 25226 tmpdir_leaked_dirs diagnosis (read-only, 2026-10-22 ET, not committed)

No runs and no spend. I didn't touch PID 3920369 or /tmp/ob-s6run (I only read files there). Helper scripts: /tmp/diag25226.py, /tmp/diag3.py.

## 1. What the change does
Diff 33f7f593ee..2283979199 in results/opencode-src/mirror touches 4 files and 14 lines:
- **core/src/global.ts**: adds `Global.Path.tmp = path.join(os.tmpdir(), "opencode")` and mkdirs it at startup.
- **agent/agent.ts**: adds `<tmp>/*` to the external_directory whitelist, so it needs no permission prompt.
- **tool/bash.ts + bash.txt**: the bash tool prompt now says "Use `${tmp}` for temporary work outside the workspace. This directory is pre-approved".

The change does not alter TMPDIR/TMP/TEMP. The runner sets those itself, to the same values on both sides (run_ab.py `scratch_env`/`_cell_scratch_tmpdir`, a per-cell root with an empty `opencode/` precreated by `ensure_empty_opencode`). So on the with side the scratch is `$TMPDIR/opencode`.

## 2. What the agent does on each side
I classified the bash permission patterns in the transcripts with /tmp/diag3.py.

| run/side | transcripts | `mktemp` used | `$TMPDIR/opencode` path used | no tmp command seen | dirs left in `opencode/` (scratch_dirs_left>0) |
|---|---|---|---|---|---|
| Opus without | 29 | 27 (21 left the dir, 6 removed it) | 3 | 2 | 0 |
| Opus with | 30 | 0 | 26 | 4 | 16 |
| Sonnet without | 30 | 10 (all 10 left the dir) | 0 | 18 | 0 |
| Sonnet with | 30 | 0 | 8 | 22 | 5 |

- **Without side:** the agent runs `mktemp -d`, which creates `$TMPDIR/tmp.XXXX`. On Opus, 20/28 scored cells also hit an external_directory rejection.
- **With side:** the agent never uses mktemp. It works in the advertised `$TMPDIR/opencode/<x>`, often leaves it behind (Opus 16/30, Sonnet 5/30), and gets no rejections.

So the with-side agent still creates tmp dirs. They sit inside the per-cell temp root but in the one subtree the metric excludes. Cleanup is not much better than on the without side.

## 3. How the metric is computed
- `run_ab.py` `_temp_dir_groups`/`leaked_temp_dir_names` count every directory under the cell's TMPDIR root **except** `opencode` and everything inside it, plus `__pycache__`. The function sits next to `scratch_env`; around line 906 is `leaked_temp_dir_names`.
- Directories inside `opencode/` go to a separate field, `scratch_dirs_left`.
- `evidence.py` `attach_cell_metrics` (around line 1960) recomputes the same split from `scratch-tmpdir.txt`.
- **Result:** the with side's scratch is excluded from `tmpdir_leaked_dirs` by construction. The change moves the dirs out of the metric's view.

## 4. Pass rates
Counts are scored cells (infra excluded) from 25226/cells and *.jsonl.

| run/side | solved | leaked cells solved | non-leaked cells solved |
|---|---|---|---|
| Opus without | 26/28 (2 hang, 2 infra) | 20/21 | 6/7 |
| Opus with | 27/30 (3 hang) | – (0 leaked) | 27/30 |
| Sonnet without | 25/30 (4 wrong_answer, 1 hang) | 8/10 | 17/20 |
| Sonnet with | 29/30 (1 hang) | – (0 leaked) | 29/30 |

Leaked cells did not fail more. The Opus failures are hangs and infra. On Sonnet, 4 of the 5 non-hang failures are the rejection-related wrong answers (see BEHAVIOUR-24974-25226.txt).

**Symmetric check (any dir left in the temp root, leaked + scratch_dirs_left):**
- Opus: 21/28 vs 16/30, Fisher p=0.107.
- Sonnet: 10/30 vs 5/30, Fisher p=0.233.

The stored headline was 21/28 vs 0/30, p=3.5e-10. Its stored numbers are unchanged; this is an alternative reading only.

## Verdict
The headline "leak 21/28 -> 0/30 / 10/30 -> 0/30" is mostly a **measurement artefact**. The metric excludes exactly the directory the PR tells the agent to use.

There is a **real behaviour change** underneath, and it is a different one:
- the agent switches from `mktemp -d` to the advertised pre-approved dir (Opus 27/29 -> 0/30 mktemp; 26/30 use opencode/);
- permission rejections disappear (Opus 20/28 -> 0/30).

With symmetric counting, I found no significant reduction in leftover tmp dirs on either model. The finding should be reported as "redirects scratch and removes permission rejections", not "fewer leaks".

No rerun is needed to decide this. If an env-only confirmation is wanted anyway, use the existing data and add a symmetric field (leaked + scratch_dirs_left) in an appended note. That costs $0.

An optional live check would be:
- the without build with the prompt line disabled but `TMPDIR` pointing at `<root>/opencode`, so mktemp lands inside the excluded subtree;
- 30 cells on Sonnet;
- about $5 (Sonnet 25226 cells cost roughly $0.15 each; check the ledger before running).
