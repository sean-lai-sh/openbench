# Stage 4 pre-registration: base agent with interchangeable modules + config-to-config parity gate

Status: DRAFT for Sean / Thesis PM review. Methods only; no code, no commits.
Author: Thesis Researcher. Date: 2026-10-30 (America/New_York).
Constraints carried in: GCP/Vertex only; open-source harnesses only (Pi, OpenCode, Hermes, ZCode, Codex; no leaked Claude Code); caps hard-suite $5K, harness study $10K, stage stop $18K.

## 0. Design in one paragraph
Instead of swapping components inside each real harness (current design), build one **base agent** whose components are modules with a fixed interface. Each OSS harness is re-expressed as a **config** (a choice of module per slot) on the base agent. Before any module-swap result is trusted, each config must pass a **config-to-config parity check** against its real harness on the same model, tasks, runner and proxy. Only configs that pass parity become "anchors"; swap effects are measured as differences between base-agent configs, and are interpreted as harness-trait effects only through a parity-passing anchor.

## 1. Parity criteria

### 1.1 Primary endpoints (both must pass; TOST, alpha = 0.05 per one-sided test, i.e. 90% CI inside the margin)
| Endpoint | Statistic | Margin | Pass rule |
|---|---|---|---|
| P1 solve rate | base-config minus real-harness, pooled over the task pack, task-stratified (Mantel-Haenszel / stratified Newcombe CI) | **±10 pp** | 90% CI of difference inside (-10, +10) pp |
| P2 tokens per cell | ratio of medians base/real (Hodges-Lehmann on log total tokens, cache-read and cache-write reported separately) | **±20%** (0.80-1.25 on the log scale, i.e. ln 1.2 symmetric) | 90% CI of ratio inside (1/1.2, 1.2) |
| P2b cost per cell | same as P2 on proxy-ledger USD | ±20% | reported; pass/fail follows P2 unless pricing differs per token class |

Scoring basis: as ruled for #196, checker timeouts / infra cells are excluded and rerun (25/70 basis, not 25/90); hangs and 2400 s kills count as agent fails. Model must match on every row (`--require-model-match`, fail-closed `model_unrecorded`). Off-protocol rows never enter parity.

### 1.2 Why these margins
- **±10 pp solve rate.** The largest harness gap we have observed on this pack so far is 4.3 pp overall (Pi 25/70 = 35.7% vs OpenCode 22/70 = 31.4%, #196, provisional). A margin wider than the between-harness differences we want to study would make parity meaningless; a margin of 10 pp is already larger than that overall gap, which is a real weakness (see 1.4). Tighter (±5 pp) needs ~1,500 cells per side per harness and is out of budget. ±10 pp is the tightest margin that is fundable; we state openly that parity at ±10 pp can certify "the base agent is not wildly different", not "the base agent reproduces a 4 pp gap".
- **±20% median tokens.** OpenCode used about 2x Pi's tokens in #196 (OpenCode $17.29 vs Pi $8.35 for the same 90 cells each). A ±20% band is an order smaller than that inter-harness spread, so token parity is a strong discriminator of whether the config really reproduces the harness's context behaviour (system prompt, tool schema, compaction, truncation). Medians, not means, because per-cell tokens are heavy-tailed.

### 1.3 Power and n (computed, not assumed)
Two-proportion TOST, true difference 0, alpha 0.05 one-sided, 80% power: n per side = (z0.95 + z0.90)^2 * 2p(1-p) / delta^2.

| p (observed range) | n per side, ±10 pp | n per side, ±15 pp |
|---|---|---|
| 0.30 | 360 | 160 |
| 0.33 | 379 | 169 |
| 0.36 | 395 | 176 |

- **The current 10 per task x 9 tasks = 90 per side is underpowered to the point of being useless for equivalence.** At n = 90, p = 0.33, ±10 pp, TOST power is ~0% (the 90% CI half-width alone is ~11.5 pp, wider than the margin). It cannot show parity even if the configs are identical.
- **Proposal: 44 per task x 9 tasks = 396 cells per side per harness** (covers p up to 0.36). Task stratification will usually shrink variance somewhat (the #196 timeouts and solves clustered by task), so this is conservative; we do not claim the design effect, we will estimate it from #196 and the reruns.
- Tokens (P2): n per side = 2(z0.95+z0.90)^2 sigma^2 / (ln 1.2)^2, sigma = SD of log tokens per cell. sigma is **not yet measured**; for sigma = 0.5 / 0.75 / 1.0, n = 129 / 290 / 516. Action: compute sigma from #196 proxy logs before freezing n. If sigma > ~0.8, P2 sets n, not P1.
- Paired-seed note: each cell is one stochastic run, so cells are independent replicates; no pairing beyond task stratification is claimed.

### 1.4 Cost implication (from #196 per-cell ledger cost only, Sonnet, this task mix)
Per-cell cost in #196: Pi $8.35 / 90 = ~$0.093; OpenCode $17.29 / 90 = ~$0.192.
| Harness | real arm 396 cells | base-config arm 396 cells (assume same cost as real if parity holds) | parity total |
|---|---|---|---|
| Pi | ~$37 | ~$37 | ~$74 |
| OpenCode | ~$76 | ~$76 | ~$152 |
| Hermes, ZCode, Codex | no per-cell data yet | | unknown: price after one 9-cell smoke each |
Caveats: (a) #196 cost is from that batch's task mix; hard-suite tasks and Opus cost far more (the H2 deferred batch hit its $501.90 stop; Opus 26821 alone was $84.95 for 180 cells in #135), so parity must stay on Sonnet unless Sean decides otherwise; (b) per-cell cost x 396 is a projection, re-project after each task and halt at the per-harness stop. Pi + OpenCode parity at ~$226 fits easily inside the $10K harness-study cap; the other three must be priced before the total is pre-registered. Proposed per-harness parity stop: 1.5x projection.

### 1.5 Per-task parity (secondary, screening, not TOST)
With 44 per task, per-task TOST at ±10 pp is not powered (needs ~380 per task). Per-task rule instead: flag any task where |base - real| >= 25 pp **and** Fisher exact p < 0.05; a flagged task blocks the swap claims that involve that task's mechanism until explained. Calibration: the regex-chess #196 split (Pi 10/10 vs OpenCode 3/10) gives Fisher p = 0.003, so a gap of that size is detectable even at n = 10; a 5-6 pp overall gap is not.

### 1.6 Behavioural parity (secondary, descriptive with pre-set flags)
- Tool-call mix: distribution over tool categories (read/search/edit/shell/plan/subagent/web); Jensen-Shannon divergence base vs real, flag if > the JSD between two real-harness A/A halves (from the VM A/A check once scored).
- Turns per cell and model calls per cell (incl. side calls: title/compaction/summary), ratio of medians within ±20%.
- Edit failure rate (edit tool errors / edits), compaction events per cell, truncation events per cell.
- System-prompt + tool-schema bytes at the proxy: must match the real harness's captured request within 5% (this is a build check, run before any scored cell).
Behavioural flags do not fail parity on their own; they must be reported and explained.

## 2. Module boundaries mapped to the 34 component rows
Source: Harness comparison sheet 1K69StE2YUIV5kowbjRY9nWJEbCr6o5Eb7HLTuA3bF6A, read 2026-10-30 via the NYU Drive connector. It has 34 feature rows across 6 layers (model/prompt 10, context 4, acting 6, control loop 5, safety 6, ops 3). Mapping is complete for all 34 rows; "Swappable" = a module slot varied in Stage 4; "Fixed" = held constant across all configs (harness-specific value only reproduced for parity); "Infra" = outside the agent, owned by runner/proxy.

| # | Layer | Sheet row | Module | Status | Notes |
|---|---|---|---|---|---|
| 1 | model/prompt | System prompt structure + length | M1 PromptAssembler | Swappable | Per-harness base prompts (e.g. OpenCode anthropic.txt 8.2 KB; Codex per-model md; Hermes SOUL.md composite). Codex prompt for a Claude model ID is "unknown -> measure at proxy" in the sheet; must be captured before its config is built |
| 2 | model/prompt | Per-task prompt variation | M1 PromptAssembler (dynamic sections) | Swappable | AGENTS.md walk-up, subdirectory hints (Hermes), dynamic sections (ZCode). Task repos must not contain AGENTS.md/CLAUDE.md unless intended |
| 3 | model/prompt | Tool count (built-in default) | M2 ToolRegistry | Swappable | Pi 7 core vs OpenCode 12 vs ZCode ~100 handlers; Codex exact count unknown (measure) |
| 4 | model/prompt | Tool schema size | M2 ToolRegistry | Swappable (derived) | Not measured for 4 of 5 harnesses; parity build check 1.6 measures it at proxy |
| 5 | model/prompt | Tool descriptor format | M2 ToolRegistry (schema renderer) | Swappable | JSON Schema variants; Codex apply_patch function vs freeform "unknown" at pin |
| 6 | model/prompt | Provider routing / Vertex | Infra: proxy | Fixed | All via Vertex proxy. ZCode and Codex have no native Vertex (Codex needs /v1/responses translation); base agent uses one route, so this row does not vary |
| 7 | model/prompt | Custom API base URL | Infra: proxy | Fixed | Required for token accounting; all five support it |
| 8 | model/prompt | Prompt caching breakpoints | M3 CachePolicy | Swappable | Affects cost not solve; P2b must report cache read/write separately. Codex sends only prompt_cache_key; adapter mapping is a confound to record |
| 9 | model/prompt | Temperature / reasoning | M4 SamplingPolicy | **Fixed** (recommend) | Hold model, temperature, thinking budget constant across configs; varying it confounds model with harness. Reproduce per-harness value only in the parity arm |
| 10 | model/prompt | Title / side model calls | M5 SideCalls | Swappable | OpenCode title call is in its cost (small_model pinned to Sonnet, `small_model_deviation=true`); parity arm must replicate that pinning |
| 11 | context | Code search | M2 tools: search | Swappable | grep/glob tools vs shell-only (Codex); LSP behind flags (OpenCode), Oh My Pi LSP not in scope unless OMP is a config |
| 12 | context | File read mode | M2 tools: read | Swappable | 2000 lines/50 KB (OpenCode, Pi) vs no read tool (Codex, via shell) |
| 13 | context | History compaction | M6 ContextManager | Swappable | Thresholds differ (OpenCode overflow-triggered; Hermes 0.50 middle-turn; ZCode 0.9 microcompact; Codex 90%). Key swap candidate |
| 14 | context | Memory files | M1 PromptAssembler (memory) | Fixed: off | Write-back memory (Hermes, ZCode) would leak across cells; disable, document as validity choice |
| 15 | acting | Edit format | M7 Editor | Swappable | Exact-string replace vs V4A apply_patch vs fuzzy. SWE-agent ablation showed edit interface matters (sec. 4) |
| 16 | acting | Shell exec / timeout | M8 Executor | Swappable (timeout) | Defaults: OpenCode 2 min, Pi none, Hermes 180 s, ZCode 120 s, Codex 10 s default. Must stay under runner watchdog (~300 s silence rule) |
| 17 | acting | Output truncation | M8 Executor (observation formatter) | Swappable | 2000 lines/50 KB vs Codex 10,000 tokens. Candidate cause of regex-chess gap (see 3.4) |
| 18 | acting | Sandbox | Infra: container | Fixed | Runner container (`h1-env`) is the sandbox for all; Codex bwrap disabled/bypassed consistently |
| 19 | acting | Web / fetch | M2 tools: web | Fixed: off | No network for tasks; Codex hosted web_search likely unavailable via Vertex anyway |
| 20 | acting | MCP / plugins | M2 ToolRegistry | Fixed: off | No MCP/plugins/skills in any config |
| 21 | control loop | Planning / todo | M9 Planner | Swappable | todo tool present (OpenCode, Hermes, ZCode, Codex update_plan) vs absent (Pi) |
| 22 | control loop | Subagents and context | M10 Delegation | Swappable | Pi none; others have subagents. Changes cost and token accounting; ledger must attribute child calls |
| 23 | control loop | Stop rules / step caps | M11 LoopController | Fixed (global cap) | Harness caps differ/unknown (Pi, Codex not found). Use one global wall/step cap from runner; record harness cap in parity arm |
| 24 | control loop | Retries | M12 RetryPolicy | Fixed | Infra noise, not a harness trait we study; same retry policy in all configs and logged |
| 25 | control loop | Error recovery / self-verify | M11 LoopController (hooks) | Swappable | Doom-loop detection (OpenCode), lint after edit (Hermes), none (Pi) |
| 26 | safety | Permission model | M13 Permissions | Fixed: allow-all | Headless benchmark; recorded per config |
| 27 | safety | Headless behaviour when it would ask | M13 Permissions | Fixed | Must never auto-reject (OpenCode `run` rejects asks unless --auto); parity arm uses the same flags as the real-harness runs |
| 28 | safety | Path guards | M13 Permissions | Fixed: off (container) | |
| 29 | safety | Destructive-command handling | M13 Permissions | Fixed: off | Could change behaviour (blocked commands); log blocks in parity arm |
| 30 | safety | Secret redaction | Infra/logging | Fixed | Not a solve factor |
| 31 | safety | Project trust | Infra | Fixed | Codex needs git repo / skip-git-repo-check consistently |
| 32 | ops | Headless CLI mode | Infra: runner adapter | Fixed | |
| 33 | ops | Token usage logging | Infra: proxy ledger | Fixed | Proxy is the source of truth for P2 |
| 34 | ops | License / source | n/a | Fixed | All MIT/Apache-2.0; all open-source, consistent with constraint |

Summary: 14 swappable slots (rows 1-5, 8, 10-13, 15-17, 21, 22, 25 grouped into modules M1-M3, M5-M11), ~20 fixed or infra. Rows 4 and parts of 1, 3, 5 have "unknown/not measured" cells in the sheet; those must be filled by proxy capture before the corresponding config can be built.

## 3. What this changes vs the current design (in-harness part swaps)

### 3.1 Gains
- **Internal validity of swaps.** In-harness swaps change one part but drag hidden couplings (prompt text referencing tools, compaction tuned to truncation). On one base agent, the only thing that changes is the module, and every config shares loop, retries, logging and proxy.
- **Full factorial becomes possible.** Any harness's editor x any compaction policy, not only the parts each harness exposes.
- **Engineering.** One adapter instead of five; no patching of five upstream codebases at pinned commits.

### 3.2 Costs / threats
- **External validity.** Results describe "trait X on our base agent", not "Pi's editor inside Pi". The thesis claim must be phrased that way; the parity gate is what licenses transfer back to the real harness, and only within the parity margins.
- **Parity is a gate, and a coarse one.** Passing ±10 pp says the config is not grossly different; it cannot certify reproduction of a sub-10 pp harness gap like the provisional 4.3 pp Pi vs OpenCode gap. Swap effects smaller than the parity margin must be reported as base-agent effects only.
- **Fidelity is bounded by unknowns.** Several sheet cells are "unknown"/"not traced" (Codex prompt for Claude, Codex tool count, Pi stop rules, ZCode error recovery). A config built over an unknown is a guess until measured.
- **Base-agent identity drift.** Module defaults chosen by us become an implicit sixth harness; it must be pinned and versioned, and the swap baseline named explicitly.

### 3.3 If parity fails for a harness
Pre-registered response, in order: (1) build check (prompt/tool bytes at proxy) and behavioural diff to localise the mismatch; (2) at most **two** documented fix iterations, each followed by a fresh parity run (prior runs kept, marked `superseded_by`, never pooled); (3) if still failing, the harness is reported as **non-reproducible on the base agent**, excluded as an anchor, and no swap claim is attributed to it. We do not widen the margin after seeing data. Each fix iteration reruns the full n (no top-up of a failed run), same rule as the 26821 and H2 rulings.

### 3.4 regex-chess as a parity stress test
Pi 10/10 vs OpenCode 3/10 (#196; Fisher p = 0.003) is the largest per-task split we have, and it alone exceeds the overall 3-solve gap. Pre-registered use: the Pi config and the OpenCode config on the base agent must each reproduce their own regex-chess rate within the per-task flag rule (1.5), and the base configs must reproduce the **direction and rough size** of the split. Prior step: read the 7 OpenCode regex-chess failures to classify real solve failures vs harness-side causes (output truncation row 17, size limits, edit format row 15). If the cause is a harness mechanism, it becomes the first pre-specified single-module swap (e.g. OpenCode config with Pi's truncation); if it is runner/infra, regex-chess is excluded from the stress test and the reason recorded.

### 3.5 What prior data stays usable
- **Real-harness arms:** Pi vs OpenCode #196 cells (after the 40 timeout cells are rerun on the #191-fixed runner) can serve as the real-harness side of parity **only if** the base-agent arm runs on the same runner commit, image, proxy, model and checker limits. Otherwise they stay as Stage 3 results and the real arm is rerun.
- **H2 / hard-suite / 26821 reruns:** remain Stage 3 evidence; they are not parity data unless their harness gets a base-agent config run under identical conditions.
- **Parts table (34 rows):** becomes the config spec; still needs Pi's column filled from proxy logs.
- **Off-protocol data** (first OpenCode gate, pre-fix 26821 run): kept, never pooled.
- **VM A/A check:** supplies the noise floor for behavioural flags.

## 4. Prior art (verified 2026-10-30)
- **SWE-Search** — Antoniades, Örwall, Zhang, Xie, Goyal, Wang. "SWE-Search: Enhancing Software Agents with Monte Carlo Tree Search and Iterative Refinement." arXiv:2410.20285. Verified via arxiv.org/abs/2410.20285. Relevance: built on moatless-tools, compares a baseline agent (Moatless-Adapted) vs search on SWE-bench Lite across five models, reporting 23% mean relative improvement and API cost per configuration (e.g. GPT-4o $40.86 vs $576.00). It is an add-a-module study on one base framework, not a cross-harness reproduction; it does **not** do parity against other harnesses. It also cites Brown et al. (2024) for high run-to-run variance of the same agent/model setup, which supports our n. Note: it reports a 1.4 pp gain from loosening state transitions on moatless (Moatless-v0.0.2 to Adapted), an example of an effect well below our ±10 pp margin.
- **SWE-agent** — Yang, Jimenez, Wettig, Lieret, Yao, Narasimhan, Press. "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering." arXiv:2405.15793. Verified via arxiv.org/abs/2405.15793. Relevance: closest precedent for single-component ablation on one agent: on SWE-bench Lite with GPT-4 Turbo, removing the edit command drops 18.0 to 10.3; edit without linting 15.0; iterative search 12.0; file viewer 30 lines 14.3 / full file 12.7; full history 15.0 vs last-5 observations 18.0. Supports making editor, search, viewer/read mode and context management swappable modules (rows 11, 12, 13, 15). Its config-file architecture (prompt templates, command files, control flow, env vars) is a precedent for configs-on-one-agent.
- **mini-swe-agent** — github.com/SWE-agent/mini-swe-agent. Verified repo page: describes itself as a ~100-line agent ("radically simple") scoring >74% on SWE-bench Verified (self-reported on the repo; model not stated on that page). Relevance: a minimal bash-only base agent is a candidate for, or a check on, our base-agent default; it also shows a shell-only agent can be competitive, relevant to Codex-style "no read/grep tool" configs.
- Not claimed: I did not verify any other modular-agent or cross-harness parity paper this pass; none is cited.

## 5. Open questions for Sean / PM
1. Margin choice: accept ±10 pp / ±20% (fundable, coarse) or pay for tighter? (±5 pp ~1,500 cells per side per harness.)
2. Parity model: Sonnet only (cheap) or also Opus? Opus parity would need its own budget line.
3. Which harnesses are anchors: all five, or Pi + OpenCode first (only ones with cost data)?
4. Base-agent implementation basis: write from scratch, or start from an existing OSS minimal agent (e.g. mini-swe-agent, MIT? license to be checked) to inherit a known baseline?
5. Can #196 real-harness cells be reused as the real arm (requires identical runner/image/proxy), or rerun real arms alongside?
6. Codex: confirm the Vertex Responses-API proxy path and the prompt it uses for a Claude model ID before including it.
7. Should Stage 4 still include a small set of in-harness swaps as an external-validity check on 1-2 base-agent swap results?

## 6. Acceptance criteria (PM can turn into issues)
1. **Base agent spec**: module interfaces for M1-M13 per section 2 table; fixed rows pinned in one config file; version hash logged per row.
2. **Config per harness**: Pi and OpenCode configs first; each lists the module choice per swappable row with a citation to the sheet's source column.
3. **Build check**: proxy capture shows system-prompt + tool-schema bytes within 5% of the real harness for each config; posted before any scored cell.
4. **Sigma measurement**: SD of log tokens per cell from #196 proxy logs, per harness; final n = max(P1 n, P2 n) frozen in this doc before launch.
5. **Smoke + pricing**: 9-cell (1 per task) smoke per real harness for Hermes, ZCode, Codex; per-cell cost posted; parity budget re-projected.
6. **Parity run per anchor**: n per side per section 1.3 (default 44 x 9 = 396), same runner commit / image / proxy / model / checker limits for both arms; `--require-model-match`; spend re-projected after each task; halt at the per-harness stop.
7. **Parity report**: P1, P2, P2b TOST CIs; per-task flags; behavioural table; regex-chess check; PASS/FAIL per anchor.
8. **Failure handling**: max two fix iterations, full-n reruns, superseded rows kept and marked.
9. **regex-chess failure read**: classification of the 7 OpenCode failures in #196 posted before the stress-test criterion is frozen.
10. **Budget ledger**: Stage 4 parity spend tracked against the $10K harness-study cap and $18K stage stop.
