# sdkpin gates 1103b: 4204 and 26821 rerun with the #223 hook fix

- Runner head: `b06e29f92392b48bd89841dc31a86db9bbd25090` (PR #237, OK'd by the Researcher). Image `h2-env:1022@sha256:72c59033…`. Host thesis-h1-cpu.
- One trial on each side, task model-extraction-relu-logits, opus. Ran 2026-11-03 18:08 to 18:14 EST.
- Spend: **$1.1886** (4204 $0.5120, 26821 $0.6766). Caps were PAIR_CAP $3 and TOTAL_CAP $5.
- No file is over 50 MB, so there is no MANIFEST.

## Pass rules (Researcher)
A gate passes only if both sides pass.
- **4204:** the hook log shows started=true and a loaded `@ai-sdk/anthropic` 2.0.0. An empty loaded list counts as unproven.
- **26821:** embedded_version is 3.0.71, and any SDK version in the user-agent header agrees with it.

## Results
| Pin | Side | Solved | load_proof | Evidence | Cost |
|---|---|---|---|---|---|
| 4204 (2.0.0) | with | yes | pass | hook started; loaded 2.0.0 from the cell cache; no other copy | $0.2552 |
| 4204 (2.0.0) | without | yes | pass | hook started; loaded 2.0.0 from the cell cache; no other copy | $0.2568 |
| 26821 (3.0.71) | with | yes | pass | embedded 3.0.71; hook started, no outside copy; no SDK version in UA | $0.2696 |
| 26821 (3.0.71) | without | no | pass | embedded 3.0.71; hook started, no outside copy; no SDK version in UA | $0.4069 |

Both gates **pass**.

## 795 / 913 / 1109: SDK pin unverified, excluded from main results

The Researcher accepted these three as **unproven**, effective 2026-11-03. No more spend and no drift reruns for them, ever. They are **excluded from main results**. 913 stays a candidate, partly *because* its pin is unproven.

Why no proof route works:
- **User-agent route:** the 1103 ledgers and rows have no SDK version in the user-agent header on any side (`loaded_anthropic` is null on all six rows). The SDK only adds `ai-sdk/anthropic/<ver>` from 2.0.18 on, and these pins are 2.0.0 betas.
- **sha256 route:** every binary is a local `bun compile` of the PR commit (`build_channel` local:compile, version string `openbench`). None of them is an OpenCode release, so no published artifact can match its hash.
  - The SDK is bundled inside the binary, so the npm tarball can't be matched against the binary either.
  - The built-in-version scan also finds nothing.
- **Hook route:** these builds predate OpenCode's plugin system (their source has no `src/plugin` directory and no plugin glob), so the #223 hook cannot load.
- **Untried idea:** compare the bundled SDK code pulled out of the binary with the npm `dist/`. Bundling probably rewrites the code, so an exact match is unlikely.
