# #245 (29236b59) Pi passthrough cache smoke (2026-11-12): SMOKE ONLY, blocked on call 1

**This is a smoke, not a result.** Nothing here is scored, poolable or usable as thesis data. Spend was $0.00.

- **Why it stopped:** Pi's own `--thinking off` sends `"thinking": {"type": "disabled"}` on the request. Both Opus 5.5 and Sonnet 5.5 rejected that with HTTP 400 on call 1, so no call 2 exists. These bodies are the ones Pi sent; the proxy changed nothing.
  - **Sonnet 5.5** (`req_vrtx_011Cgyo3jVqFdtcKD739Ji7v`): `To turn thinking off on this model, send "thinking": {"type": "between_tools"} instead of {"type": "disabled"}. The model does not think before responding. The short updates it writes between tool calls come back as thinking blocks.`
  - **Opus 5.5** (`req_vrtx_011Cgyo4TeNaQoPwm5xzSsbT`): `"thinking.type.disabled" is not supported for this model. Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.`
- **No request bodies at that head:** the Vertex proxy at `29236b59` does not save Anthropic request bodies (only the Responses API path does). The two call-1 bodies in `raw/cells/*/pi/requests/` were captured by this smoke's launcher wrapper (`raw/m245p-batch.py`), not by the proxy. For the same reason, the earlier re-smoke (`results/matched245-resmoke-1112`) has no bodies, and its per-call prefix divergence can't be computed.

## Setup
- **Pins and VM:** same as `results/matched245-resmoke-1112`: thesis-h1-cpu-2, head `29236b59`, regex-chess.
- **Pi config:** `OBENCH_MATCHED_CONFIG=1` stayed set, so Pi got its matched 200K context and `--thinking off`.
- **No body edits:** the proxy's body injection (`apply_disabled_thinking`) was replaced at launch time in the cell process (`raw/m245p-batch.py`). The replacement writes the outgoing body (`json.dumps(parsed)`, the exact bytes forwarded) to `pi/requests/NNNN.request.json` and edits nothing. No repo file was changed.
- **What the proxy still does:** the usual identity and sampling-param stripping, which was also there in #196.

## Result
On both models, Pi's first request carried **`"thinking": {"type": "disabled"}` from Pi itself**: `--thinking off` maps to `disabled`. Vertex returned 400 on the first call, with the same bodies as `results/matched245-smoke-1112`:
- **Sonnet 5.5:** `To turn thinking off on this model, send "thinking": {"type": "between_tools"} instead of {"type": "disabled"}. ...` (`req_vrtx_011Cgyo3jVqFdtcKD739Ji7v`)
- **Opus 5.5:** `"thinking.type.disabled" is not supported for this model. Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.` (`req_vrtx_011Cgyo4TeNaQoPwm5xzSsbT`)

So a pure passthrough with the matched Pi settings can't get past call 1, and no cache or divergence data exists for calls 2 and on.

## Breakpoints in Pi's call-1 body (`breakpoints-call1.txt`)
All three use `cache_control {type: ephemeral}`. Offsets are into `json.dumps(body)`, whose key order is model, messages, max_tokens, stream, system, tools.

| location | Sonnet bytes | Opus bytes |
|---|---|---|
| `tools[3]` (the 4th of 5 tools) | 7548–8087 | 7546–8085 |
| `system[0]` | 1865–4742 | 1863–4740 |
| `messages[0].content[0]` (the last user block) | 73–1811 | 71–1809 |

## Re-smoke comparison
The re-smoke proxy at this head does not save Anthropic request bodies; only the Responses API path does. So `matched245-resmoke-1112` has no bodies, and the per-call divergence offsets can't be computed from its logs.
