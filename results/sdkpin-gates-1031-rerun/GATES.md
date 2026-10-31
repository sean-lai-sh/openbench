# SDK-pin gates 1031 rerun

- **Code:** main 8da1614b (#221 is merged, so the vertex proxy records `loaded_anthropic` from the `ai-sdk/anthropic/<ver>` User-Agent).
- **Image:** h2-env:1022@sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff.
- **Task:** model-extraction-relu-logits, opus, 1 trial per arm.
- **Caps:** PAIR_CAP $1.00 and TOTAL_CAP $6.03 (cumulative), with no per-cell cap.
- **Quarantine tag:** `sdkpin_gate_1031`.
- **Driver:** `thesis/ab/h2env/sdkpin_gate_drive.sh`. Its log is in `driver.log` and spend is in `spend.log`.
- **Times:** EDT (UTC-4), Oct 31 2026.

## Rule
- **Pass:** `loaded_anthropic` == pin on both arms.
- **Fail:** a mixed value or a mismatch.
- **Unproven:** no UA. A pair stopped by the $1 pair cap is cap-stopped and unproven, not failed.

## Results

| Pin | PR | Loaded (with / without) | Result | Pair cost |
|---|---|---|---|---|
| 2.0.0-beta.5 | 913 | null / null | **unproven** (the SDK sends no suffix, see below) | $0.6574 |
| 2.0.0 | 4204 | null / null | **unproven** (the SDK sends no suffix) | $0.5793 |
| 2.0.25 | 3052 | 2.0.25 / 2.0.25 (ledger: 12× 2.0.25) | **pass** | $0.5017 |
| 2.0.50 | 5140 | 2.0.50 / no row (ledger: 20× 2.0.50) | **cap-stopped, unproven** (stopped at $1.0138; the "without" arm was killed) | $1.0903 |
| 2.0.58 | 13331 | 2.0.58 / 2.0.58 (ledger: 11× 2.0.58) | **pass** | $0.8168 |
| 2.0.58 | 13090 | 2.0.58 / 2.0.58 (ledger: 15× 2.0.58) | **pass** | $0.8679 |
| 3.0.71 | 26821 | null / null | **unproven** (opencode v1.15.2 overrides the UA, see below). Counts toward the 3.0.71 $250. | $0.5096 |

- **Held:** 2.0.0-beta.4 (795) and 2.0.0-beta.11 (1109) were not run. They would be unproven because their SDK source sends no suffix.
- **UA probe:** $0.0003, in `ua-probe/`.
- **Total spent (gatewatch, all of this dir):** $5.0232 of $6.03.
- **2.0.0 raw-SSE stop basis:** not reached, because the gate is unproven on the UA alone.

## Source findings (`~/h1/opencode-src/provider-pins/<pin>/node_modules/@ai-sdk/...`)

**No UA suffix: beta.4, beta.5, beta.11 and 2.0.0.** In `@ai-sdk/anthropic/dist/index.mjs`, the provider `getHeaders` returns only these headers:
```
const getHeaders = () => ({
  "anthropic-version": "2023-06-01",
  "x-api-key": loadApiKey({ ...
```
That code is at these lines:
- 2.0.0-beta.5: line 1866
- 2.0.0: line 1890

None of the four have a `VERSION` constant or `withUserAgentSuffix`. Their provider-utils versions also have no `withUserAgentSuffix` (0 hits):
- 3.0.0-beta.2 (beta.4 and beta.5)
- 3.0.0-beta.8 (beta.11)
- 3.0.0 (2.0.0)

**Suffix present: 2.0.25, 2.0.58 and 3.0.71.**
- **2.0.25:** `var VERSION = true ? "2.0.25"` (line 13), `getHeaders = () => withUserAgentSuffix(` (line 2546), `` `ai-sdk/anthropic/${VERSION}` `` (line 2556). Uses provider-utils 3.0.11.
- **2.0.58:** the same code at lines 14, 3310 and 3320. Uses provider-utils 3.0.20.
- **3.0.71:** the same code at lines 15, 5275 and 5281.

**Where it first appears:** the 2.0.58 CHANGELOG puts `322901b: feat: add provider version to user-agent header` under **2.0.18**. So the suffix first appears in @ai-sdk/anthropic 2.0.18, and every pin ≤ 2.0.17 is structurally unprovable by UA.

**Opencode's bundled path:**
- The opencode source has no `ai-sdk/anthropic/` string. The only `withUserAgentSuffix` uses are in its openai-compatible and copilot providers. So opencode never adds the suffix itself.
- In the newer opencode (v1.15.2, commit 548648a, PR 26821), `packages/opencode/src/session/llm.ts:361-374` passes a per-call `"User-Agent": \`opencode/${InstallationVersion}\`` header to `streamText`. Call headers override the provider's suffixed UA, so the proxy sees no `ai-sdk/anthropic/` token even though 3.0.71 sets one. The cell rows log `cell missing required fields ['loaded_anthropic']`.
- The opencode versions behind 3052, 5140, 13331 and 13090 did not override it, and their ledgers carry the version.

## Raw User-Agent probe (`ua-probe/`)
I ran `uaprobe.py` in h2-env:1022. It loads the pinned `@ai-sdk/anthropic` directly under bun 1.3.13 (not through opencode) and makes one `doGenerate` ("Reply with OK.", maxOutputTokens 8, opus). A tee logs the raw request headers (API key removed) and forwards to the real vertex proxy, whose ledger is in `ua-probe/proxy-ledger/`.

| Pin | Raw User-Agent | Proxy ledger loaded_anthropic |
|---|---|---|
| 2.0.0-beta.5 | `Bun/1.3.13` (Bun's default; the SDK sets none) | absent |
| 2.0.58 | `ai-sdk/anthropic/2.0.58 ai-sdk/provider-utils/3.0.20 runtime/bun/1.3.13` | `2.0.58` |

Each call was 15 input and 4 output tokens, $0.0003 in total.

## Implication
The UA rule can only prove pins ≥ 2.0.18, and only in opencode versions that do not override the per-call User-Agent. Gating betas, 2.0.0 or 3.0.71 under opencode ≥ v1.15 needs another proof of the loaded version, for example module-resolution logging inside the cell. That is not done here.
