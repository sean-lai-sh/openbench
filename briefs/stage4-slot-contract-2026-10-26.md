# Stage 4 slot contract: genome framework for harness component swaps (2026-10-26)

Scope: Stage 4, $10K cap, GCP/Vertex inference only. Harnesses: OpenCode c10134729d, Pi d0aa218, Hermes 4dcef215, ZCode 3c5b2276 (v3.16.2), Codex CLI rust-v0.164.0 (6aaac694). Companion table: `stage4-slot-contract-2026-10-26.csv` (34 rows, one per row of `harness-components-2026-10-24.csv`).

## 1. Sources and gaps
- The slot list comes only from `harness-components-2026-10-24.csv/.md` (34 rows). No slots were invented. The CSV keeps each harness's stock value next to the classification.
- The "Pi as chassis" recombination sketch in `harness-components-2026-10-24.md` is **superseded**. Slots now live inside each stock harness, and there is no shared base harness.
- Gaps carried over from the source as "needs check" (17 slots; see CSV `needs_check`):
  - Codex: tool count, apply_patch format, step cap, self-verify, and which prompt it picks for Claude
  - Pi: title calls, step cap, retries
  - ZCode: headless ask, reasoning values
  - Hermes and ZCode: read and truncation caps
  - Whether compaction and subagent switches are set by config or hard-coded
- Row 4 (tool schema size) is unmeasured for all five harnesses. It must be measured at the proxy, from the request body, in the A/A runs.
- Not read for this brief: `harness-comparison-prereg.md` and the step8 D2/D3/D4 deviation briefs. The PM should cross-check the pins and the retry and fault-counting policy against them.

## 2. Classification (34 slots)
| Class | n | Slots |
|---|---|---|
| transferable-across-harnesses | 7 | sys_prompt, code_search, read_caps, edit_format, shell_timeout, output_truncation, planning_todo |
| swappable-within-harness | 8 | ctx_injection, toolset, cache_breakpoints, side_calls, compaction, subagents, step_cap, self_verify |
| pinned-excluded | 19 | tool_schema_size, tool_descriptor_format, provider_route, base_url, sampling, memory_files, sandbox, web, mcp_plugins, retries, permissions, headless_ask, path_guards, destructive_cmd, secret_redaction, project_trust, headless_cli, usage_logging, license |

What each class means:
- **Transferable:** the variant is either a parameter value (caps and timeouts) or a self-contained tool or text module with plain file or text IO. "Transplant" means a native re-implementation behind the same interface, not running another harness's code.
- **Swappable:** the change is a toggle or threshold in the harness's own code path.
- **Pinned:** infrastructure, safety rails, or a model setting. These are held identical and logged, never varied.

## 3. Module contract (every variant)
1. **Interface.** A variant is `{slot_id, variant_id, harness, kind: param|text|tool|toggle, payload, applies_via: config|env|patch|flag}`.
   - Patches are applied to the pinned harness sha, and the patch file is hashed.
   - A `tool` variant declares its name, its JSON schema, and its IO (files touched, and stdout format).
   - It must not change any other slot's surface. In particular, it must not change the tool list unless the slot is `toolset`/`code_search`/`planning_todo`.
2. **Default = stock.** The variant `default` for every slot in every harness produces no diff, no added env, and no flags beyond the adapter's pinned flags.
   - The all-defaults genome must produce a first request body that is **byte-identical** at the proxy to unmodified stock: system prompt, tools array, and params. The comparison uses sha256 of the request body after normalising timestamps and UUIDs.
3. **Smoke test (1 cell).** Run one fixed task with the variant and assert an observable taken from the proxy log or the transcript. A cell whose assertion fails is an error, not a datapoint. Example assertions:
   - sys_prompt: hash of the system block equals the hash of the variant text
   - toolset/code_search/planning_todo: tool names in the request
   - edit_format: the edit tool's schema, plus at least one call to it
   - read_caps/output_truncation: truncation marker at the configured size
   - shell_timeout: a sleep task killed at N s
   - cache_breakpoints: cache_control positions in the body, or cache_read tokens > 0
   - side_calls: count of tagged auxiliary requests
   - compaction: a summary request at the threshold
   - step_cap: termination at cap on a forced loop
4. **Logging per cell:**
   - Identity: `genome_hash` (sha256 of canonical JSON, sorted keys, no whitespace), `genome_json`, `framework_sha`, `harness`, `harness_pin`, `patch_hashes[]`
   - Loaded versions: `provider_version_loaded` (actual package version, e.g. OpenCode's runtime install), `model_id`, `region`
   - Smoke and fidelity: `slot_id`, `variant_id`, `smoke_assertion`, `smoke_pass`, `first_request_sha`
   - Proxy usage: input, cache_read, cache_write, output and aux tokens, request count, faults
   - Run: `task_id`, `seed/run_idx`, `wallclock`, `outcome`
5. **Fail closed.** Abort the cell, with no retry under a different config, if any of these happens:
   - the genome names an unknown slot or variant, or a slot that is pinned
   - a transferable variant targets a harness not in its `harnesses_implementing` list
   - the patch doesn't apply cleanly
   - `provider_version_loaded` ≠ pin
   - `first_request_sha` mismatch on the defaults genome
   - smoke fails
   - the proxy saw no traffic, or traffic bypassed the proxy
   - a "needs check" slot is used before its check is closed

## 4. Combination rules (order)
1. **Phase 0, equivalence.** Per harness, the all-defaults genome passes byte-identity, then an A/A test (30 vs 30 runs). The difference CI must sit inside that harness's A/A band (Sonnet reference: +0.1% [−6.5, +6.8]). Until this passes, no swaps count.
2. **Phase 1, single-slot.** Change one slot per genome, everything else default.
   - Order: run the parameter slots first (cheap, low risk), then text, then tool, then toggle.
   - Within a harness, sort by the expected token effect, largest first: cache_breakpoints, compaction, side_calls, output_truncation, read_caps, edit_format…
3. **Phase 2, combinations.** Only slots that showed an effect alone (CI excludes 0, preregistered) may be combined, and only within one harness, at most 2–3 slots per genome.
   - Slots marked "no" in `combinable_phase2` (ctx_injection, cache_breakpoints, compaction, subagents) stay single-slot.
4. **Phase 3, transplant.** Move a transferable slot's winning variant into another harness. Each transplant needs its own smoke test there and is reported as a new arm, never pooled with native results.

## 5. Gates → PRs
- **PR1: Registry.** Contents:
  - `slots.yaml` generated from this CSV (id, class, harnesses, variants, smoke assertion)
  - a validator (rejects pinned or unknown slots and needs-check slots)
  - a per-harness applier stub

  Accept when the registry loads all 34 rows, rejects the bad genomes in tests, and every swappable or transferable slot has a smoke assertion.
- **PR2: Genome file and hashing.** Contents: JSON schema, canonicalisation, `genome_hash`, and cell log fields (§3.4) written by the runner. Accept when:
  - the hash is stable across key orderings
  - a defaults genome hashes the same for all harnesses, modulo the harness id
  - the logs contain every field
  - a missing field fails the cell
- **PR3: Equivalence check.** Contents: a proxy first-request diff tool, plus an A/A runner (30×2 per harness, with CI output). Accept when:
  - byte-identity passes for all five harnesses (ZCode and Codex through their gateway or `/v1/responses` path)
  - the A/A CI is inside the band
  - the report is committed with the genome hash and framework sha

## 6. Prior art and adoptions
- **SWE-agent ACI configs** ([config](https://swe-agent.com/latest/config/config/), [tools](https://swe-agent.com/latest/reference/tools_config/), [custom tools](https://swe-agent.com/latest/usage/adding_custom_tools/); arXiv 2405.15793). Tools are bundles: a directory holding a `config.yaml` with signature, docstring and args, plus `bin/` and `install.sh`. The agent YAML lists the bundles it uses.
  - *Adopt:* make each tool variant a bundle directory with a manifest, and hash the directory into `patch_hashes`.
  - *Pitfall:* SWE-agent is now maintenance-only, which shows that config surfaces drift. That is why we pin the sha.
- **mini-swe-agent** ([docs](https://mini-swe-agent.com/latest/), [YAML](https://mini-swe-agent.com/latest/advanced/yaml_configuration/)). About 100 lines, bash only, linear history. The config has agent/environment/model/run keys, and `agent_class` is an import path.
  - *Adopt:* separate the genome into those four sections so a model or env change can never hide inside a "harness" slot.
  - *Possible use:* as a minimal reference harness for sanity checks. It is outside Stage 4 scope.
- **OpenHands SDK** (arXiv 2511.03690; [architecture](https://docs.openhands.dev/sdk/arch/overview), [custom tools](https://docs.openhands.dev/sdk/guides/custom-tools)). The agent core, tools, workspace and server are separate packages. Each tool is a typed Action/Observation/Executor.
  - *Adopt:* every tool variant declares typed action and observation schemas, and the smoke test validates observations against the schema.
  - *Adopt:* the workspace (sandbox) sits outside the genome, which matches pinning `sandbox`.
- **DSPy** (arXiv 2310.03714; [modules](https://dspy.ai/current/api/modules/), [signatures](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/learn/programming/signatures.md)). A Signature declares the IO contract, and Modules implement it. Optimizers rewrite prompts against a metric.
  - *Adopt:* define each slot as a signature, and require each variant to implement it. This is the module contract in §3.1.
  - *Pitfall:* optimised prompts are fitted to a training set. Any prompt variant we take from an optimiser must be frozen before the held-out tasks are run.
- **ADAS** (arXiv 2408.08435; [code](https://github.com/ShengranHu/ADAS)). Meta Agent Search writes agents in code and keeps an archive. It searches on a small validation split (e.g. ARC 20 val / 60 test) and reports results on held-out data.
  - *Pitfall:* with an open code search space, wins can't be attributed to a component. AFlow's App. B.2 critiques its search.
  - *Adopt:* the archive idea, as an append-only log of every genome hash and its result. Our closed slot vocabulary avoids the attribution problem.
- **AFlow** (arXiv 2410.10762; [code](https://github.com/FoundationAgents/AFlow)). MCTS over code workflows with a fixed operator set. Each round makes a single-step modification. Each candidate is evaluated 5×. Model, temperature and format are fixed. Early stop when the top-k is unchanged. Split is 20/80 val/test, seed 42.
  - *Pitfall:* the val set is filtered to high-variance problems, so it is not representative. Workflows found with one model did worse with another.
  - *Adopt:*
    - a single-slot change per step
    - repeated evaluation (≥5 per cell in search, 30 in confirmatory runs)
    - pinned model and sampling
    - a seeded task split fixed in the prereg
    - stopping rules declared up front
    - any winning genome re-checked on the second model before claiming it generalises
- **SWE-Search** (arXiv 2410.20285; [code](https://github.com/aorwall/moatless-tree-search)). MCTS with value and discriminator agents on moatless-tools, reporting a ~23% relative gain on SWE-bench Lite.
  - *Pitfall:* its "adapted" baseline also changed state transitions (+1.4%), a confound mixed in with the gain. Cost rose sharply (GPT-4o $40.86 → $576), so they added a compute-matched Pass@5 comparison. They also cite high variance across repeated runs.
  - *Adopt:*
    - the A/A gate guards against a confounded baseline
    - report tokens and $ per cell, and compare against compute-matched baselines (best-of-k on default) whenever a variant raises cost by more than 1.5×

## 7. Open items for PM
- Close the 17 needs-check slots by reading the source at the pinned shas, before PR1 accepts those slots.
- Confirm the retry and fault policy against the D4 brief.
- Measure row 4 (tool schema size) during PR3.
