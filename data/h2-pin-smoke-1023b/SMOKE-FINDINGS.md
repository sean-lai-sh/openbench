# H2 pin-smoke 2026-10-23 (ET)

Runner tip: `e2ac6b75` (#126). Image: `h2-env:1022`. VM: `thesis-h1-cpu`.

## Gate (required)

| PR | gate | pin want | toolchain anthropic | sdk_drift | result |
|---|---|---|---|---|---|
| 4204 | alias / equality | 2.0.0 | 2.0.0 | none | PASS |
| 13331 | outdated / isOutdated | 2.0.77 | 2.0.77 | none | PASS |

Out dir: `~/h2/h2-pin-smoke-1023b` (and box `results/h2-pin-smoke-1023b/`).
One task (`dna-insert`) × 1 trial × both sides. Cells may be `wrong_answer`; pin gate only cares about toolchain + no sdk drift.

## First attempt (invalid env) — `h2-pin-smoke-1023`

Deferred bun versions were missing from `~/h1/opencode-src/bun/` (had 1.2.14/1.2.21/1.3.14/1.4.2 only).
`bun_for_checkout` path not a file → proxy omits `bun` → `_ensure_provider_sdk` no-ops.

| PR | observed | note |
|---|---|---|
| 4204 | anthropic **4.0.87** | equality-gate binary installed `@latest`; sdk drift |
| 13331 | anthropic **missing** | outdated/bundled path; sdk drift |

Fix applied before re-smoke: `ensure_bun` for 1.3.2, 1.3.3, 1.3.5, 1.3.8, 1.3.13.

## Deferred batch

Cleared after both PASS. Fresh out: `~/h2/h2-deferred-1023`. Finished H2 cells in `h2-hardsuite-1022` untouched (still runner 980e71b6 artifacts).
