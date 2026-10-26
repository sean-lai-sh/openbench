# SC-1 addendum: resolving "needs check" slots (2026-10-26)

This addendum resolves the slots flagged "needs check" in `stage4-slot-contract-2026-10-26.md`. The original brief is unchanged. Detail is in `stage4-slot-contract-SC1-addendum-2026-10-26.csv`: 49 rows, one per slot×harness, each with its citation.

## Pins (all five checked out at the pinned commit; no fallbacks to a release tag were needed)
| Harness | Repo | Commit |
|---|---|---|
| OpenCode | sst/opencode | c10134729dd2ce00beb18604ec91f10319f59a78 |
| Pi | badlogic/pi-mono | d0aa218cb16c333c008f6aa3dcd670ac8b68383c |
| Hermes | NousResearch/hermes-agent | 4dcef215cfe41bd2d02c2d1dad6e257a18101216 |
| ZCode | zai-org/ZCode | 3c5b227649371507ddc4eb46ac5133afe6db1cab |
| Codex | openai/codex | 6aaac694803004a63c6f393d153c96d22521a6b9 (rust-v0.164.0) |

Method: grep plus reading the code at each pin. "Absent" means no hits for the search terms. It does not prove the feature is missing. The clones were deleted after this pass.

## Findings that change the design
1. **Codex + Claude uses fallback metadata** (`model_info.rs:98-156`). Codex doesn't recognise the Claude model name, so it falls back to generic settings:
   - Base prompt is `prompt.md`.
   - The shell runs through `exec_command`/`write_stdin`.
   - **No `apply_patch` tool is registered** (`spec_plan.rs:1409-1412`), so edits go through the shell.
   - Truncation is **10,000 bytes**, not 10k tokens.
   - The context window is assumed to be **272k**, but Claude's is 200k. Auto-compaction triggers at 90% of the window, so it would fire too late for Claude.

   **Adapter must set `model_context_window`.** Log the Codex arm as "fallback ModelInfo".
2. **Codex `update_plan` is off by default** (`config/mod.rs:2791-2797`), yet `prompt.md:54-60` tells the model to use it. That mismatch is part of the stock baseline and stays in.
3. **OpenCode pruning is off by default** (`compaction.ts:275` returns unless `compaction.prune`). This corrects the 10-24 brief's "prunes beyond 40k".
4. **Pi's default toolset is read/bash/edit/write.** grep, find and ls exist but are off (`settings-manager.ts:85`). code_search therefore becomes a toolset toggle in Pi.
5. **Hermes compaction threshold is 0.50, floored to 0.75** for windows under 512K, so it is effectively 0.75 for Claude. Hermes also makes auxiliary title-generation calls by default.
6. **ZCode has a bash sandbox mode** (`contracts/src/tools/bash.ts:64-69`). This corrects "no sandbox found". In headless `-p` runs it defaults to `yolo` (`cli/src/run.ts:52`).
7. **No step cap by default in four of the five harnesses** (Pi, Codex, Hermes, OpenCode). ZCode's main loop isn't confirmed (see Unresolved).

## Reclassifications vs the original brief
None of the 34 slots changes class. Two slot×harness cells are narrowed (rows 1–2 below), and two cells are notes rather than changes (rows 3–4). The CSV records the details:

| Slot | Harness | Change |
|---|---|---|
| edit_format | Codex | Transferable, but only as an **added** tool. Stock has no edit tool for Claude. |
| code_search | Pi, Codex | Implemented as a toolset add, not a parameter. |
| tool_descriptor_format | Codex | Stays pinned. The question is moot because apply_patch isn't registered. |
| sandbox | ZCode | Stays pinned. Fix the value to the `yolo`/sandbox state the adapter uses and log it. |

**Cleared:** sys_prompt, ctx_injection (OpenCode), cache_breakpoints, side_calls, read_caps, output_truncation, compaction, step_cap, headless_ask, retries (Pi), project_trust (Hermes).

## Unresolved
- **ZCode:**
  - reasoning/thinking defaults (`sampling`)
  - the subagent on/off switch
  - the main-loop step cap
  - how todo is coupled to plan mode
- **Hermes:**
  - no off-switch found for subdirectory hints
  - verification_stop: whether it is on by default
- **Codex:** exact default tool count. It depends on feature flags, so capture it at the proxy.
- **Row 4, tool schema size: not measured statically.** Codex, OpenCode and ZCode assemble their tool schemas at runtime from features and model metadata. Measure the `tools` array bytes from the first request at the proxy in PR3 (equivalence check).
