# Harness components: Pi, OpenCode, Hermes, ZCode, Codex CLI (2026-10-24)

Read-only brief, Thesis Researcher. The full feature matrix (34 rows, 6 layers, one source per cell) is in `harness-components-2026-10-24.csv`.

## Sources (pinned)
| Harness | Identified as | Source used | Pin | License |
|---|---|---|---|---|
| OpenCode | sst/opencode **1.x** (`packages/opencode/src`, v1.18.31); H2's pin | git clone | **c10134729d** (c10134729dd2ce00beb18604ec91f10319f59a78, 2026-09-20). Column refreshed from 2.x core 7ba0e4b on 2026-10-24 | MIT |
| Pi | badlogic/pi-mono `packages/coding-agent` | git clone | d0aa218 (2026-10-24) | MIT |
| Oh My Pi | can1357/oh-my-pi (Pi fork, "batteries included") | README only | 0b5c27a | MIT |
| Hermes | **NousResearch/hermes-agent** (confirmed: toolsets, delegate_task, compression, docs at hermes-agent.nousresearch.com) | git clone | 4dcef215 | MIT |
| ZCode | **zai-org/ZCode** (Z.ai's open-source harness for GLM-5.3, created 2026-09-20). No other serious candidate found | git clone, `apps/zcode-cli/packages/core/src` | 3c5b2276 (v3.16.2) | Apache-2.0 |
| Codex CLI | **openai/codex** (`codex-rs`, Rust CLI; added 2026-10-24 per Sean as 5th open-source harness) | git clone | **rust-v0.164.0** (6aaac694803004a63c6f393d153c96d22521a6b9, tagged commit 2026-10-22 23:15 ET); latest non-alpha release tag | Apache-2.0 (LICENSE + NOTICE) |



Claude Code is removed from the study entirely (Sean, 2026-10-24: open harnesses only). It is closed source, contributes no parts, and has no Stage 3 runs or adapter (prereg A2). Oh My Pi is README-only context, not a CSV column.

**Codex CLI notes.** Codex talks to models only over OpenAI's **Responses API** (`wire_api = "chat"` was removed; `codex-rs/model-provider-info/src/lib.rs:102`). Our proxy (PR #128) only serves `/v1/chat/completions`, so reaching Vertex needs a **`/v1/responses` endpoint** in the proxy; the Developer adds it in the Codex adapter PR. Point Codex at it with a custom `[model_providers.<id>]` `base_url` (`lib.rs:146`). Headless: `codex exec "<prompt>" --json --skip-git-repo-check --ephemeral`; exec forces `approval_policy=never` (`exec/src/lib.rs:589-591`), so it never blocks on a prompt, but its default sandbox is read-only. On our externally sandboxed VM/Docker cell use `--dangerously-bypass-approvals-and-sandbox` (or `--sandbox workspace-write`), recorded per arm. Its hosted `web_search` tool is OpenAI-side and probably won't work through Vertex; check at smoke.

## Key findings for the hard-suite run
1. **Proxy token counting is possible for all five (Codex via a Responses-API endpoint).** Each one supports a custom base URL (CSV row "Custom API base URL").
2. **Vertex is not native in ZCode or Codex.** Codex needs a proxy Responses endpoint (above). ZCode only ships `@ai-sdk/anthropic`, `openai`, and `openai-compatible` (`adapters/package.json:104-106`), so running it on Vertex needs a gateway that translates to an OpenAI-compatible or Anthropic-compatible API. **This is a blocker to resolve before running.**
3. **Pi is the minimal baseline.** It has 7 tools, no permission prompts, no todo tool, and no subagents (docs/security.md says it "does not ask for approval"). ZCode and Hermes sit at the heavy end, with large tool catalogs, deferred tools and tool-search, and memory write-back.
4. **Truncation and timeout defaults differ, and that confounds token comparisons.** OpenCode and Pi both use 2000 lines / 50 KB. Bash timeouts (OpenCode at 1.x pin c10134729d): Pi has none by default, Hermes 180 s, ZCode and OpenCode 120 s, Codex 10 s default when the model sets none (`exec.rs:63`), with 10k-token output cap. **These should be either pinned to the same values or logged per run.**
5. **Compaction policy differs** (OpenCode at the 1.x pin compacts on overflow with a 20k-token reserve and prunes old tool output beyond 40k tokens, ZCode microcompacts at 0.9, Codex auto-compacts at 90% of the context window, Hermes summarizes with a cheap model at a threshold). On long tasks this alone could drive the token gap.
6. **Some harnesses make side model calls** (OpenCode title plus separate compaction/summary agent calls, Hermes auxiliary client, ZCode compaction/memory agents, Codex compaction requests and optional guardian auto-review). These must be counted separately at the proxy, or they will inflate the "harness cost" numbers.

## Unknowns / not verified
- Tool schema size in bytes isn't measured for any harness. Hermes maintainers mention a ~44 KB tools array. **I recommend measuring all five at the proxy on the first request.**
- Codex: exact default tool count, apply_patch descriptor format, which base prompt it picks for a Claude model ID, title calls, step cap and self-verify are **unknown**; measure at proxy/smoke.
- Pi: temperature, step cap, and retries weren't traced. OpenCode (1.x pin): `opencode run` verified; headless it auto-rejects permission asks unless `--auto`/`--dangerously-skip-permissions` is passed, so the adapter must set that flag. Secret redaction not found. ZCode: no sandbox found (it relies on permission gating instead). These cells read "not traced" or "not found in this pass", which means absent from my grep, not proven absent.

## SWE-Search (note)
SWE-Search (Antoniades et al., arXiv 2410.20285, 2024) wraps a SWE agent (moatless-tools) in Monte Carlo Tree Search. A value agent scores states using numeric plus qualitative feedback, and a discussion agent debates candidate solutions. It reports roughly a 23% relative gain on SWE-bench Lite over the same agent without search. *These details are from memory; I didn't re-fetch the paper this turn, so verify before citing.*

## Recombination ("genetic" cross-section) sketch
Treat each CSV row as a gene with 2–5 alleles, one taken from each harness. Examples: edit format (exact-replace / multi-edit / V4A patch), compaction (reserve% / microcompact / cheap-model summary), read cap, shell timeout, subagents (none / fresh-context child / restricted toolset), tool exposure (native list / CodeMode / deferred plus tool-search).
- Use **Pi as the chassis**, because it's minimal and MIT-licensed and its extension API (docs/extensions.md) can add each allele. Then run a fractional-factorial or evolutionary search, with fitness = pass rate − λ·tokens on the hard suite. SWE-Search's MCTS could then be applied per task on top of the best genome.
- Keep these genes behind the same proxy and pre-registered rules as H2. Search cost scales with genome count × 9 tasks × 10 per side, it is funded from the ~$9K Stage 4 reserve in prereg A2 and sized in its own Stage 4 pre-registration.
