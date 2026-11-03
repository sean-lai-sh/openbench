# Stage 4 pre-registration: cross-harness part search (v1 DRAFT)

Status: DRAFT for Sean / Thesis PM review. Methods only; no code, no data seen. Author: Thesis Researcher. Written 2026-11-03 (America/New_York) against `sean-lai-sh/openbench` main `b4abce28`.
Fulfils harness-comparison-prereg A2 §5 ("Stage 4 sizing (population, generations, screening subset, winner reruns), fitness and selection rules go in a separate Stage 4 pre-registration").

**Convention.** Every number below is either cited to a repo brief / PR, computed here (formula shown), or marked **[PD]** = *proposed default*, not grounded in repo data, for Sean to accept or change.

Inputs read: `briefs/stage4-prereg-base-agent.md` (#197), `stage4-slot-contract-2026-10-26.md` (+ SC-1 addendum, AD-1 note), `harness-components-2026-10-24.md/.csv`, `harness-comparison-prereg.md` (v1 + A1, A2), `findings-by-test-1029.md`, `step8-amendment-machine-move-2026-10-25.md`.

## 0. Design in one paragraph
We search over **genomes**: a stock parent harness (Pi, OpenCode, Hermes, ZCode or Codex CLI, at the slot-contract pins) with one or more **slots** filled by a variant taken from another of those harnesses, e.g. *Pi with OpenCode's `compaction`*. Genomes follow the slot contract (#158) exactly: variant schema, `default = stock` (stock = plain harness + AD-1 fixes), fail-closed rules and per-cell logging. Claude Code contributes nothing (A2 §0, §5). Each candidate is scored on the hard suite by **completion rate** and **tokens per solved task** (harness-comparison A1 definitions), run **separately for Opus 5.5 and Sonnet 5.5**. The search optimizes tokens per solved task subject to success not falling more than a margin below the parent; it runs on a **search task split**, and only the final winner(s) and their parents are rerun on a **held-out task split** for the confirmatory claim.

### 0.1 Relation to the base-agent prereg (#197)
#197 proposed one base agent with harnesses re-expressed as configs plus a parity gate. The agreed design (Sean, restated in room 2026-11-03) instead slots parts **inside real harnesses**, which is the slot-contract design. This prereg therefore **supersedes #197 §§0–3 as the Stage 4 design**. Kept from #197: the ±10 pp / ±20 % margin reasoning, the within-task token σ measurement (Pi 0.37 / OpenCode 0.31, #196), the per-cell cost figures, and the "two fix iterations, no margin widening" rule (reused in §3.3). The base-agent parity runs (~$226) are **not** part of this plan unless Sean keeps them as a side study (Q1 in §10).

## 1. Prior art (verified 2026-11-03 on arxiv.org/abs/2410.20285)
- **SWE-Search** — Antoniades, Örwall, Zhang, Xie, Goyal, Wang. "SWE-Search: Enhancing Software Agents with Monte Carlo Tree Search and Iterative Refinement." arXiv:2410.20285. A multi-agent framework on moatless-tools: **MCTS over an agent's actions/states within a single task trajectory** (modified UCT), an LLM Value Agent giving value plus natural-language feedback, and a Discriminator Agent that debates final solutions. On SWE-bench Lite (300 instances) it reports a 23 % mean relative resolve-rate gain over its Moatless-Adapted baseline across five models; Moatless-Adapted itself differed from Moatless-v0.0.2 by a 1.4 % change from looser state transitions; API cost rose sharply (GPT-4o $40.86 → $576.00), and Appendix J gives compute-matched Pass@5 baselines. Search caps: max 100 iterations, 3 expansions per node.
- **How we differ.** SWE-Search searches *at inference time, per task*, over trajectories of one fixed agent; its output is a patch. We search *offline, across tasks*, over **harness configurations** built by recombining parts of five existing harnesses; our output is a harness, evaluated by ordinary single-trajectory runs. We use no value model and no LLM judge: fitness comes from the task checker and the proxy ledger. What we adopt from it: (a) report tokens/$ per cell, because search-style changes can multiply cost; (b) watch for baseline confounds like its 1.4 % adapted-baseline shift (our A/A gate, §3.1); (c) its citation of Brown et al. (2024) on high run-to-run variance supports repeated cells per candidate.
- Other prior art (SWE-agent, mini-swe-agent, OpenHands SDK, DSPy, ADAS, AFlow) is cited as already summarised in the slot contract §6 and #197 §4; I did **not** re-verify those this pass, and nothing new is cited.
- "SWE-Search-style" in the room means *search*, not MCTS per se. The search here is an evolutionary (μ+λ) loop (§5) because candidates are discrete slot assignments, not trajectory states.

## 2. Search space
- **Parts pool:** the 34 rows of `harness-components-2026-10-24.csv`, classified in the slot contract: **7 transferable** (sys_prompt, code_search, read_caps, edit_format, shell_timeout, output_truncation, planning_todo), **8 swappable-within-harness** (ctx_injection, toolset, cache_breakpoints, side_calls, compaction, subagents, step_cap, self_verify), **19 pinned** (never varied).
- **Cross-harness transplants** (the agreed "Pi with OpenCode's X" candidates) use the 7 transferable slots; a transplant is a native re-implementation behind the slot interface (slot contract §2). Within-harness toggles of the 8 swappable slots are allowed as mutations, with the contract's `combinable_phase2 = no` rule for ctx_injection, cache_breakpoints, compaction, subagents (single-slot only).
- **Note on the example.** `compaction` is classed swappable-within-harness, not transferable, so "Pi with OpenCode's compaction" is **not** a legal genome under the current contract. Either compaction is reclassified as transferable by a dated contract amendment before launch, or the example becomes e.g. "Pi with OpenCode's `output_truncation`". Open question Q3.
- **Needs-check slots** (17, slot contract §1) cannot be used until closed (fail-closed rule).
- **Upper bound of first-order transplants per parent:** 7 slots × 4 donors = 28 (fewer where donor variant = parent stock or donor not in `harnesses_implementing`).

## 3. Validity before fitness
### 3.1 Phase 0 per parent harness × model (slot contract §4.1, AD-1)
1. AD-1 fixes merged and a 1-cell smoke shows each took effect in proxy logs.
2. All-defaults genome byte-identical to stock at the proxy (`first_request_sha`).
3. A/A 30 vs 30 on the scored VM; difference CI inside that harness's A/A band. Until passed, no candidate of that parent counts.

### 3.2 Per-candidate validity gate (before any fitness is computed)
A candidate is **INVALID** (discarded, logged, not scored as a loss) if any of:
- a slot-contract fail-closed condition fires (unknown/pinned/needs-check slot, patch doesn't apply, `provider_version_loaded` ≠ pin, smoke assertion fails, proxy saw no traffic);
- **any scored cell shows a protocol error caused by request content**: an upstream 4xx whose cause is the request the genome built (e.g. thinking-signature 400s, as in 3052 Sonnet's 3 signature 400s and 5140 filter-js, `findings-by-test-1029` H2), malformed tool schema, or message-ordering rejection;
- model mismatch on any row (`--require-model-match`, fail-closed `model_unrecorded`).
Gate order: smoke (1 cell) → first evaluation batch; a protocol error at any point invalidates the whole candidate and all its cells move to `invalid_cells` (kept, never pooled). The archive records `genome_hash, invalid_reason, first_bad_cell, spend`. Invalid rate per slot and per donor is reported as a finding (a part that breaks the protocol on another harness is a result, not noise).

### 3.3 If a parent fails Phase 0
At most two documented fix iterations (each a full A/A rerun, prior runs marked `superseded_by`); then the parent is reported as non-equivalent and excluded as a parent (donor parts may still be used if their smoke passes on the recipient). No band widening after data (#197 §3.3).

## 4. Fitness (two objectives, constrained)
Per candidate *c* with parent *P*, same model, on the **search split**, scored cells only:
- **Success** s = passes / scored cells (infra rows excluded; 2400 s kills, hangs and give-ups = fail; harness-comparison §8, #196 ruling).
- **Efficiency** T = total proxy tokens / passes ("tokens per solved task", harness-comparison A1). Main-agent-only T and $ per pass reported alongside; side-call tokens counted in total (AD-1 Hermes rule).
- **Feasible** iff s_c ≥ s_P − m_search, with **m_search = 10 pp [PD]** (same margin #197 argued is the tightest fundable). With passes = 0, T is undefined → infeasible.
- **Rank:** feasible candidates by T ascending (lower is better); infeasible ones after all feasible, by s descending. Ties broken by $ per pass, then genome_hash.
- Rationale: findings so far show success barely moves (no efficiency PR moved easy-suite pass rate; largest harness gap 4.3 pp provisional) while tokens differ ~2× (OpenCode $17.29 vs Pi $8.35 per 90 cells, #196). So the search optimizes the axis that moves and guards the one that doesn't.
- **Caveat stated now:** at 25 cells per candidate (§5) a 10 pp feasibility check is a screen, not a test; selection noise is handled by elite re-evaluation (§5.4) and the held-out confirm (§7), never by claiming search-phase significance.
- **Compute-matched check (slot contract §6):** any finalist whose $ per cell exceeds the parent's by > 1.5× is also compared to best-of-k of the parent at equal spend.

## 5. Search procedure
### 5.1 Task split (fixed before any Stage 4 cell)
The hard suite has 9 tasks (harness-comparison-prereg). Split **5 search / 4 held-out [PD]**, drawn with `random.Random(20261103).sample(sorted(tasks), 4)` for held-out **[PD seed]**; log list + sha256 before the first scored cell. No task is dropped post hoc. Weakness: 4 held-out tasks is a thin generalisation test (Q5).

### 5.2 Parents and order
Pi and OpenCode first (the only harnesses with cost data, #196); Hermes, ZCode, Codex join as parents once their Stage 3 baselines and Phase 0 pass **[PD; was #197 Q3]**. All five are donors from the start, subject to smoke on the recipient. Each model (Sonnet 5.5, Opus 5.5) runs its own independent search; no genome is carried across models before the held-out confirm (AFlow lesson, slot contract §6).

### 5.3 Generations
- **Eval unit:** 5 runs per search task × 5 tasks = **25 cells per candidate [PD]** (slot contract adopts "≥5 per cell in search").
- **Gen 1 (single-slot):** every legal first-order transplant per parent (≤28), order per slot contract §4.2 (param → text → tool → toggle; largest expected token effect first).
- **Gen 2…G (recombination), per parent lineage:** keep **μ = 4** best (by §4 rank) **[PD]**; produce **λ = 8** children **[PD]**:
  - *crossover:* union of two elites' slot assignments (conflicting slot → pick one at random, seeded), dropped if > 3 non-default slots (contract §4.3 cap) or if it combines a non-combinable slot;
  - *mutation:* add, swap the donor of, or revert-to-default one slot, uniform over legal moves;
  - duplicates (same genome_hash) are not re-run; their archived score is reused.
  - Seeds: `random.Random(20261103 + generation)` **[PD]**, logged.
- **Archive:** append-only, every genome_hash with its cells, fitness, invalid_reason.

### 5.4 Stopping rules
Search for a (parent, model) lineage stops at the first of:
1. **G_max = 4 generations** including Gen 1 **[PD]**;
2. the top-μ set unchanged for **2 consecutive generations [PD]** (AFlow-style early stop);
3. lineage spend reaches 1.5× its projection (§8) **[PD, same factor as #197]**;
4. global caps (§8).
Then **elite re-evaluation:** the top 3 feasible genomes per lineage get +10 runs per search task (50 cells) **[PD]**; the winner is the best by §4 on pooled 75 cells. A lineage with no feasible genome reports "no winner".

## 6. Pins, machines, rows
- Harness pins and AD-1 fixes as in the slot contract header; fixed runner commit, image digest and proxy commit per stage, written to every row; a change needs a dated amendment before the next scored cell.
- **Load-proof per row:** `loaded_anthropic == pin` (#218/#221), `load_proof_basis` recorded (#223, #227). A row without load-proof is not scored.
- **Scored cells on GCP VMs only**, `vm_name` and `instance_id` on every row (#225). **Mac mini machines (Claude-driven builds) may build and test code but never produce scored cells**; any cell whose row lacks a GCP VM id is rejected.
- **Pooling across VMs** only after that VM passes the A/A check (`step8-amendment-machine-move`: stock OpenCode vs itself, Sonnet 5.5, 30 per side; pool only if the 95 % CI overlaps +0.1 % [−6.5 %, +6.8 %]); otherwise that VM's cells are analysed separately.
- **Infra rows** (upstream_error / stream break, checker timeouts, VM/docker faults; harness-comparison §8) are uncounted and rerun, up to 2 reruns per cell; counts reported per candidate.
- Interleaving: within a generation, cells of all candidates are shuffled with the generation seed so load hits all equally.

## 7. Confirmatory test on the held-out split
Arms per (lineage, model): **winner vs its stock parent**, same VM pool, interleaved.
- **H1 (success, non-inferiority):** winner success ≥ parent − 10 pp. One-sided α = 0.05, task-stratified (Mantel-Haenszel / stratified Newcombe).
- **H2 (tokens, superiority), tested only if H1 passes (fixed-sequence, no alpha split):** ratio of tokens per cell winner/parent < 1, task fixed effect on log total tokens, two-sided α = 0.05; tokens per solved task reported with bootstrap CI (10k, cells within task, seed 20261103 [PD]).
- **Stated effect and n (computed):** n per side = 2(z_{.975}+z_{.80})² σ² / (ln r)².
  - r = 0.8 (a 20 % token cut **[PD]**; comparable to the −19..−29 % Sonnet 26821 hard-task effects in findings-by-test-1029 and below the ~2× Pi/OpenCode spread): σ = 0.37 → 44; σ = 0.5 → 79; σ = 0.8 → 202.
  - NI success at 10 pp, 80 % power, one-sided 0.05: n per side = (z_{.95}+z_{.80})²·2p(1−p)/0.1² → p 0.30: 260, 0.33: 274, 0.36: 285.
  - **H1 sets n: 288 per side = 72 per held-out task [PD rounding of 285 up to a multiple of 4].** That also powers H2 for σ up to 0.8 at r = 0.8.
- Re-check σ on the held-out tasks' Stage 3 data before launch; if within-task σ > 0.8 revisit (#197 rule).
- Generalisation across models (exploratory): each model's winner is also run on the other model at the same n only if budget remains (§8 line "cross-model", optional).

### 7.1 Multiple comparisons
- Search-phase numbers are **selection, not inference**: no p-values reported for search-split comparisons; they're labelled exploratory.
- Confirmatory family = (lineages with a winner) × 2 models, each with the H1→H2 fixed sequence. **Holm across the family within each hypothesis** (max 4 with Pi + OpenCode lineages; more if other parents join, size fixed before the held-out run).
- Per-task held-out results descriptive only (no per-task tests; the H2 control-lights-up issue in findings-by-test is why).
- Slot-level attribution (which part drove the gain) is exploratory: report the winner's one-slot-removed ablations on the search split only if budget remains.

## 8. Cost projection
Per-cell rates from repo data: Sonnet Pi ≈ $0.093, Sonnet OpenCode ≈ $0.192 (#196, hard pack); Opus OpenCode ≈ $0.47 (26821, #135). **Opus Pi and all Hermes/ZCode/Codex rates are unknown**; Opus Pi is projected at the Opus OpenCode rate as a conservative placeholder **[PD]**, and the other three harnesses are excluded until a 9-cell smoke prices them.

| Phase (per model; Pi + OpenCode lineages) | cells | Sonnet | Opus |
|---|---|---|---|
| Phase 0 A/A 30v30 × 2 parents | 120 | ~$17 | ~$56 |
| Smokes, 1 cell per legal variant (≤56) | ≤56 | ≤$8 | ≤$26 |
| Gen 1, ≤28 × 2 × 25 | ≤1,400 | ≤$200 | ≤$658 |
| Gens 2–4, 8 × 2 × 25 × 3 | 1,200 | ~$171 | ~$564 |
| Elite re-eval 3 × 2 × 50 | 300 | ~$43 | ~$141 |
| Held-out 288 × 2 arms × 2 lineages | 1,152 | ~$165 | ~$541 |
| Subtotal | ≤4,228 | **≤~$604** | **≤~$1,986** |
| Infra-rerun allowance 10 % **[PD]** | | ~$60 | ~$199 |

**Projected Stage 4 total (Pi + OpenCode lineages, both models): ≈ $2.85K**, of which Opus ≈ 76 %. Hermes/ZCode/Codex lineages would each add an unpriced amount; re-project after their smokes. Sonnet costs are averaged across lineages ((0.093+0.192)/2 ≈ $0.14 for shared rows).
Caveat: hard-suite per-cell cost varies a lot by task and model (H2 deferred batch hit its $501.90 stop); re-project after every generation.

**Caps:** Stage 4 draws on the **$10K harness cap** (Stage 3 + Stage 4 combined, A2 §4; Stage 3 estimated ~$300–600). **Stage stop $18K** across everything. Per-lineage stop 1.5× projection [PD]; check-ins with Sean at 50 % and 90 % of the Stage 4 projection [PD]. Cumulative spend at launch must be read from the proxy ledger; I did not compute it here. The new $5K (hard suite + reruns) is not drawn on unless Sean says so.

## 9. Acceptance criteria (PM → issues)
1. **Contract amendment** (if Sean wants compaction transplants): dated reclassification of `compaction` (and any other slot) before launch.
2. **Close needs-check slots** used by Gen 1 (source reads at pins), recorded in the slot CSV.
3. **Registry + genome + equivalence PRs** (slot contract PR1–PR3) merged, with a new validator rule rejecting genomes > 3 non-default slots or combining non-combinable slots.
4. **Validity gate PR:** per-candidate classifier from proxy logs marking `invalid_reason` (protocol 4xx incl. thinking-signature, schema reject, model mismatch, smoke fail) vs `infra` (5xx/stream break/checker timeout); unit tests using the 3052 signature-400 rows as fixtures.
5. **Search loop PR:** (μ+λ) loop with seeded crossover/mutation, archive (append-only, keyed by genome_hash), dedup, stopping rules §5.4, per-lineage spend stop; dry-run on stubbed scores.
6. **Row guards:** runner rejects any scored row without GCP `vm_name/instance_id`, load-proof, or matching image/proxy/runner commit; Mac mini hosts can't write scored rows.
7. **Task split frozen:** list + sha256 committed before the first Stage 4 cell.
8. **Phase 0 report** per parent × model (byte identity, A/A CI), committed with framework sha.
9. **Pricing smokes** for Hermes, ZCode, Codex (9 cells each), then a re-projection posted.
10. **Per-generation data PR** with archive diff, invalid table, spend vs projection.
11. **Held-out confirm report:** H1/H2 with Holm, tokens per solved task, $ per pass, invalid and infra counts, compute-matched check where triggered.
12. **Budget ledger** against $10K harness cap and $18K stage stop, updated each data PR.

## 10. Open questions for Sean
1. **Base-agent study (#197):** drop it (this prereg replaces it), or keep its ~$226 Pi + OpenCode parity runs as a side check? *(Replaces #197 Q4 base-agent basis and Q7 in-harness check, which no longer apply: the search already runs inside real harnesses.)*
2. **Margin** (#197 Q1, still applies): accept 10 pp for both feasibility and held-out non-inferiority? Tighter costs more (5 pp ≈ 4× the held-out n).
3. **Compaction:** reclassify as transferable so "Pi with OpenCode's compaction" is legal, or keep the contract as is?
4. **Parent order** (#197 Q3, still applies): Pi + OpenCode first, others after pricing — OK?
5. **Held-out split:** 5/4 split of 9 hard tasks is thin. Accept, or add held-out tasks from another pack (would need its own calibration)?
6. **Reuse** (#197 Q5, adapted): may Stage 3 primary-run cells serve as the parent baselines on the search split if runner/image/proxy are identical, saving Gen 0 cost?
7. **Codex** (#197 Q6, still applies): include as parent/donor only after the `/v1/responses` Vertex route and its Claude prompt are confirmed.
8. **Search sizes** μ = 4, λ = 8, G_max = 4, 25 cells/candidate, elite +50: accept the proposed defaults?
9. **Budget:** Stage 4 on the $10K harness cap (not the new $5K) — confirm. Opus is ~3/4 of projected spend; run Opus search in full or only confirm Sonnet's winners on Opus?
*(#197 Q2 "Sonnet only?" is resolved: both models run separately.)*
