# Step-8 F03-2 probe_method results (2026-10-27, PR #166)

No model calls; every run went to the local stub. Image `h1-env:1027-strace`.

## Control 0dc80df6: PASS
- Embedded `@ai-sdk/anthropic` (read by `obench/provider_embedded.py` from the bundle path `node_modules/.bun/@ai-sdk+anthropic@2.0.58+d6123d32…/…/dist/index.mjs`, cross-checked with `var VERSION5 = "2.0.58"`):
  - rebuild (`s8ctl-f04`, sha256 a3a64611…): **2.0.58**
  - original (`h1/opencode-src`, sha256 563bb048…): **2.0.58**
- Requests (`c0dc/request_compare.txt`): each binary sent 2 × `POST /v1/messages`, one to claude-haiku-4-5 (title, no tools) and one to claude-opus-5-5 (12 tools, same body keys). They arrive in different orders, so they are paired by (method, path, model). Endpoint, method, body shape and tool list all match.
  - The only content differences are the per-run temp workdir path in the bash tool description and the `workdir` parameter description, the same volatility as the Working directory line.
- This time both binaries took the "provider options" assess route. On 10-26 the original took ANTHROPIC_BASE_URL.

## Bundled-provider sides among the 22 F03-2 sides: none
`embedded_scan.tsv`: no F03-2 binary contains an `@ai-sdk/anthropic` bundle, and the probe recorded `probe_method=strace` on all 22. The only bundled binaries are the 0dc80df6 control's.

## Readiness, all 22 sides (`f21/`, `f3481/`)
- 21/22 were ready on the first pass. 3481 used the local-channel builds.
- 3251/without failed once with "no request reached stub": the assess route flipped to ANTHROPIC_BASE_URL, and the request went past the stub (`invalid x-api-key`, rejected, no spend). Two reruns (`f3251r1/`, `f3251r2/`) were ready 2/2 each. This route flip is intermittent and also appeared on 0dc80df6 on 10-26.
