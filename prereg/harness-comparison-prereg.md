# Harness comparison (Stage 3): pre-registration v1
Fixed 2026-10-24 (ET), before any harness-comparison cell or smoke cell has run. Read-only research brief (Thesis Researcher); not committed.
Builds on `hard-suite-prereg-v2.md` (incl. Amendments A1, A2) and `harness-components-2026-10-24.md` / `.csv` (34-row component matrix).
Anything not changed here inherits v2's rules (exclusions, blocked status, 2400 s cap, VM logging, DEFERRED handling).

## 1. Question
On the 9-task hard suite, how do five coding-agent harnesses, each **as shipped (own defaults)**, compare on tokens, cost, pass rate and wall time when the model, tasks, machine, scorer and token counting are held fixed?

## 2. Arms (harnesses), pinned
| Arm | Project | Pin (record exact commit/version + sha256 of built artifact at Stage 2 merge) | Model path |
|---|---|---|---|
| **Pi (baseline)** | badlogic/pi-mono `packages/coding-agent` | d0aa218 (brief pin; final pin = adapter PR) | Vertex via proxy |
| OpenCode | sst/opencode | **c10134729d** (c10134729dd2ce00beb18604ec91f10319f59a78, v1.18.31, 1.x line), the same pin H2 used. Decided 2026-10-24, before any data: kept for comparability with H2, and the adapter cannot run 2.0 (A1). Parts-table column refreshed at this pin (not 2.x 7ba0e4b). Headless runs need `--auto`/`--dangerously-skip-permissions` or asks are auto-rejected | Vertex via proxy |
| Hermes | NousResearch/hermes-agent | 4dcef215 (or adapter-PR pin) | Vertex via proxy |
| ZCode | zai-org/ZCode | 3c5b2276 (v3.16.2) | Anthropic-compatible endpoint **inside our proxy** → Vertex (gateway PR lands first) |
| Claude Code | official `@anthropic-ai/claude-code` CLI, headless `claude -p` | 2.1.310 (or version installed at adapter PR) | `ANTHROPIC_BASE_URL` → proxy → Vertex. No leaked source used anywhere |

Version pins (harness commit/version, adapter commit, runner commit, proxy commit, image digest, model IDs/versions on Vertex) are written to every cell record. A pin changes only via a dated amendment made before any scored cell of that arm.

## 3. Models, tasks, size
- Models: Claude Sonnet and Claude Opus on Vertex, same model IDs for all arms (record exact IDs).
- Tasks: all 9 in `data/packs/openbench-tb-hard/pack.toml` (dna-insert, filter-js-from-html, model-extraction-relu-logits, polyglot-rust-c, regex-chess, sam-cell-seg, torch-pipeline-parallelism, torch-tensor-parallelism, video-processing). **No substitutions and no post-hoc dropping of tasks**; a task held back for infra goes to DEFERRED.txt and is run later.
- Primary run: 5 arms × 2 models × 9 tasks × 10 runs = **900 cells**.
- Budget: hard cap **$1,000**, check-in with Sean at **$600** (spend counted at the proxy). Counts toward the $18K stage stop. If the cap would be hit before completion, stop and report; no arm or task is dropped to fit budget. Completion of a reduced design requires a dated amendment.

## 4. Primary condition: own defaults
Each harness runs with its shipped defaults (shell timeout, output/read caps, compaction trigger and method, side calls, sub-agents, memory files, reasoning settings), except what is needed to run headless and on our model path:
- model/base URL pointed at the proxy; headless/non-interactive flags; permission mode set to the least-prompting headless option the harness documents (recorded per arm) so no cell blocks on a prompt;
- no AGENTS.md/CLAUDE.md or other project memory files present in task repos unless the task ships them (same for all arms).
- **Uniform limit:** 2400 s per cell; hitting it = **fail** (v2 A1). Applies to Pi even though Pi has no shell timeout of its own.

Logged per cell: effective shell timeout, output/read cap, compaction trigger (and number of compactions fired), number and type of side calls, sub-agent calls, step/turn count, reasoning setting, permission mode.

## 5. Secondary condition (optional, separate approval)
Matched-settings run: shell timeout 120 s and a common output cap (modal value across arms) where the harness exposes them; non-settable values logged. Size and budget set in its own amendment; reported separately and never pooled with the primary run. Not required for the primary conclusions.

## 6. Schedule, seeds, machine
- All cells on the same GCP VM type, Docker exec, shared warm image (torch cache baked in, v2 A2).
- Order: cells interleaved across arms, seeded: build list of (arm, model, task, run) and shuffle with `random.Random(20261024)`; log list + sha256 before the first scored cell. Concurrency fixed and logged; start/end times, VM type, runner commit per cell.
- Harness-internal randomness: temperature/sampling left at defaults (recorded); no per-run seed is claimed where the provider doesn't support one.

## 7. Smoke criteria (per arm, per model; not scored)
One smoke cell per arm × model (10 total) on a single fixed task (polyglot-rust-c, as in v2). An arm passes smoke when: it runs headless to completion without a prompt hang; every model call goes through the proxy and is tagged main vs side; token and cost fields are non-null; the scorer reads its result; all section-4 settings are logged. Smoke failures are fixed in the adapter before the primary run; smoke outcomes are not analysed. The Stage 2 adapter order (proxy gateway → Pi → OpenCode → Hermes → ZCode → Claude Code) is unchanged.

## 8. Cell statuses and exclusions (inherits v2)
- **pass / fail**: scorer result. Timeout at 2400 s, hang, crash of the agent, or giving up = fail.
- **infra**: environment/VM/runner/proxy fault not caused by the agent (e.g. Docker failure, VM loss, proxy 5xx unrelated to request content). Excluded and re-run, up to 2 reruns per cell; counted and reported per arm.
- **blocked** (A2): provider content filter refused. Excluded from pass rate and token analysis, counted and reported per arm × model; a noticeably higher blocked rate in one arm is reported as a finding.
- Classification rules are applied by script from logs, before unblinding the arm-level summaries where possible. No other exclusions. Excluded-cell counts appear in every table.

## 9. Metrics
1. **Total tokens** per cell (all calls through proxy: input + output + cache read/write reported separately and summed).
2. **Main-agent-only tokens** (proxy-tagged; side calls = title, summary/compaction helper, memory, small/fast model excluded).
3. **Cost** per cell (Vertex list prices at proxy, price table pinned).
4. **Pass rate** per (arm, model, task).
5. **Wall time** per cell.
Report both "all scored cells" and "completed cells only" for tokens (as in v2).

## 10. Analysis (pre-specified)
- **Comparisons:** each of OpenCode, Hermes, ZCode, Claude Code **vs Pi**, per model (4 × 2 = 8 comparisons per metric). No other pairwise tests are confirmatory; anything else is exploratory and labelled so.
- **Token / cost / wall time:** ratio arm / Pi of per-task means, combined as the geometric mean across the 9 tasks; 95% CI by bootstrap (10,000 resamples, cells resampled within (arm, model, task), seed 20261024). p-values from the bootstrap (two-sided), **Holm-corrected within each metric family of 8**. Effect = Holm-adjusted p < 0.05; per-task ratios also reported.
- **Pass rate:** Fisher's exact test per (comparison, task), reported only on tasks where the **pooled baseline (Pi) pass count is 2/10..8/10** for that model; other tasks reported descriptively. Holm across the reported Fisher tests in each model. Unadjusted p in 0.01–0.05 is labelled **borderline**; screen-level only (n=10).
- Primary token metric for headline claims: main-agent-only tokens; total tokens reported alongside. Side-call share reported per arm.
- Covariates are descriptive only: logged settings (timeout, cap, compaction, side calls) are used to explain gaps, not to adjust the primary test.

## 11. Predictions (recorded, not tested as hypotheses)
Pi lowest tokens per cell (fewest tools, no sub-agents); Hermes and ZCode highest total tokens, partly side calls; Claude Code and OpenCode in between. No directional pass-rate prediction.

## 12. Deviations
Any change after the first scored cell is a dated amendment stating what was seen at the time. Results reported regardless of direction.

## Amendment A1 (2026-10-24, before any harness data)

Added at Sean's request to track hard-suite completion and token efficiency as headline numbers. Descriptive headlines; they do not replace the pre-registered Holm-corrected comparisons vs Pi.

For each harness × model:
1. **Completion:** overall pass rate across all 9 hard tasks (passes / scored cells, blocked excluded), Wilson 95% CI. Tasks are not dropped.
2. **Tokens per solved task:** total tokens / passes, bootstrap 95% CI (10k resamples, resampling cells within task). Also reported with main-agent tokens only. Dollars per pass reported alongside. If passes = 0, reported as "no solves" (undefined), not infinity.

## Amendment A2 (2026-10-24, before any smoke data)

Written 2026-10-24 (ET) at Sean's request, before any smoke cell or scored cell of any arm has run. No harness-comparison data has been seen.

0. **Claude Code removed from the study entirely** (Sean, 2026-10-24: open harnesses only, everywhere). It is closed source; it has no Stage 3 arm, no reference runs and no adapter. Its §2 row (pin 2.1.310) and every Claude Code mention in §§2, 7, 10 and 11 are void.
1. **New arm: Codex CLI** (openai/codex, Apache-2.0), the 5th open-source harness, taking Claude Code's place. Pin **rust-v0.164.0** (commit 6aaac694803004a63c6f393d153c96d22521a6b9, latest non-alpha release tag at time of writing); final pin = Codex adapter PR, recorded per cell as in §2. Model path: Vertex via proxy through a **Responses API endpoint** (`/v1/responses`), because Codex only speaks the OpenAI Responses API (`codex-rs/model-provider-info/src/lib.rs:102`); the endpoint is added in the Codex adapter PR. Headless: `codex exec --json --skip-git-repo-check --ephemeral`; exec forces `approval_policy=never` (`exec/src/lib.rs:589-591`). Because the cell is already sandboxed in Docker on the VM, the arm runs with `--dangerously-bypass-approvals-and-sandbox` (least-prompting headless option, §4); recorded per cell. Codex's OpenAI-hosted `web_search` tool is left at default and its availability through the proxy is logged, not patched. Stage 2 adapter order becomes proxy gateway → Pi → OpenCode → Hermes → ZCode → Codex CLI; Codex smoke follows §7 (still 10 smoke cells: 5 harnesses × 2 models).
2. **Size:** Stage 3 primary run stays **5 arms (Pi, OpenCode, Hermes, ZCode, Codex CLI) × 2 models × 9 tasks × 10 runs = 900 cells**. Pi stays the baseline.
3. **Analysis:** comparisons are each of OpenCode, Hermes, ZCode, Codex CLI vs Pi, per model: **4 × 2 = 8 comparisons per metric**; Holm family size in §10 stays **8** (Codex replaces Claude Code). The Fisher pass-rate rule and A1 headline metrics apply to Codex unchanged.
4. **Budget (replaces §3 budget line):** total cap **$10,000** for Stage 3 + Stage 4 combined (Sean, 2026-10-24), counting toward the $18K stage stop; spend counted at the proxy. Stage 3 (900 cells) is estimated at **~$300–600**. Codex's 180 cells replace Claude Code's 180, so the cell count stays at 900 and there is **no net cost delta** (~$0.33–0.67/cell; Codex's 180 cells ≈ $60–120 of the total, same share Claude Code had). Actual Codex per-cell cost may differ with its prompt, compaction and tool defaults; tracked at the proxy. The remaining **~$9,000 is reserved for the Stage 4 genetic search** on Opus 5.5 and Sonnet 5.5. PM check-ins at **$2,000** and **$5,000** of run spend. The rule that no arm or task is dropped to fit budget still holds.
5. **Stage 4 parts pool: open source only:** Pi, OpenCode, Hermes, ZCode, Codex CLI. **Claude Code is excluded as closed source**: it contributes no genes, and no leaked or "community" copy of its source is used. Stage 4 sizing (population, generations, screening subset, winner reruns), fitness and selection rules go in a separate Stage 4 pre-registration written after Stage 3 baselines exist. Goal (Sean): explore to find the best harness.
6. **License check (from each repo's LICENSE file):** Pi MIT, OpenCode MIT, Hermes MIT, ZCode Apache-2.0, Codex CLI Apache-2.0 (with NOTICE). None blocks reusing or recombining components; Apache-2.0 parts must keep their license/NOTICE text and mark modified files.
