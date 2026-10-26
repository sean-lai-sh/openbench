# Stage 4 slot contract: AD-1 adapter-fix note (2026-10-26)

This note adds to `stage4-slot-contract-2026-10-26.md` (#158, 43423ec8) and the SC-1 addendum. It defines what counts as "stock" when an adapter fix is needed for a harness to run correctly on Claude via Vertex.

## Rule 0: stock = plain harness + AD-1 fixes
Each AD-1 fix redefines that harness's stock baseline. The A/A equivalence check (FW-3) compares plain harness + AD-1 fixes against the framework's all-defaults genome, never against raw upstream. Every fix is disclosed in the thesis methods section and logged per cell (`adapter_fixes` field: list of fix ids).

## AD-1 fixes
1. **AD1-codex-ctx:** Codex falls back to a 272k context window for unknown models (`models-manager/src/model_info.rs:98-156`). Set `model_context_window=200000`. This is a correctness fix: without it auto-compaction (90%) fires after Claude's real limit. Becomes part of Codex stock.
2. **AD1-codex-edit (no change):** Stock Codex on Claude registers no `apply_patch` (`core/src/tools/spec_plan.rs:1409-1412`), so edits go through the shell. Do NOT add an edit tool in AD-1; shell-edit stays the default. Adding `apply_patch` is an `edit_format` swap variant. Record the observed edit path and the 10,000-byte output truncation in the cell log.
3. **AD1-zcode-sandbox:** ZCode headless `-p` defaults to `yolo` (`cli/src/run.ts:52`). Pin the sandbox mode to whichever mode matches the other harnesses on our runner (container-level isolation, no in-harness approval prompts), and log the mode per cell. A mismatch fails closed.
4. **AD1-hermes-side:** Hermes title-generation side-model calls stay ON as stock. The proxy tags them (`call_role=side`) and their tokens are reported separately from main-loop tokens; primary token metrics include both, with a main-only sensitivity column.

## Gates
- No non-Pi A/A check runs until its harness's AD-1 fixes are merged and a one-cell smoke shows each fix took effect in proxy logs.
- Any further adapter fix found later is added here as AD-2+, with the same disclosure and logging, before it affects scored cells.
