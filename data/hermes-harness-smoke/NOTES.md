# Hermes arm notes (PR #240)

Investigation of the hard-suite arm at pin
`4dcef215cfe41bd2d02c2d1dad6e257a18101216`, without a Vertex call.
`db46b354` was not assumed to have passed: its VM smoke is inaccessible
(expired gcloud). The live cell is still required before any scored run.

## What the last recorded smoke showed

`fa92664b` (before the 200K window and the beta strip): cache reads
`[0, 0, title 0]` and server thinking tokens `[2565, 139, 0]`.
Check 2 fails because main call 2 read nothing. Check 3 fails because the
two main calls thought. The title call thought 0 tokens.

An earlier cell (`df4934f90f6f8d26`, locked in
`obench/tests/test_smoke_evidence.py`) had the same call-2 miss, then main
call 3 read exactly the prefix call 1 wrote (`17159`). That is the
region-split signature on the Vertex `global` endpoint. OpenCode shows the
call-2 miss in 28 of 90 reference cells. The pass rule is unchanged. The
endpoint is not changed here.

## Thinking off is a research decision

At this pin (`agent/anthropic_adapter.py`):

- Adaptive Claude thinks when `thinking` is omitted. `agent.reasoning_effort`
  left unset resolves to no `thinking` field. That matches the smoke's
  `thinking_sent=none` plus thousands of server thinking tokens.
- Sonnet 5.5's documented off is `thinking: {type: between_tools}`
  (`reasoning_effort: none`): no up-front thinking, short notes between tool
  calls. `thinking: {type: disabled}` 400s on that model.
- Opus 5.5 rejects a disable (`_MANDATORY_THINKING_CLAUDE_SUBSTRINGS`). An
  explicit off still omits the field, so it keeps thinking.
- `between_tools` is folded into `thinking_sent=none` by the proxy, but the
  strict check also requires exactly 0 server thinking tokens on every call.
  `between_tools` is defined to still emit notes, so sending it would change
  the request and still may fail check 3.

The arm does not send `between_tools` or `disabled`. `harness_settings`
records this as `thinking_off_status`.

## What the beta strip does

`AD1-hermes-beta` drops `interleaved-thinking-2025-05-14` from the
`anthropic-beta` header before the proxy forwards. It keeps
`fine-grained-tool-streaming-2025-05-14`. The request body is not given a
`thinking` field. A header strip cannot turn off a model that thinks when
the field is absent. The proxy replay test locks that: cache markers stay,
and no thinking object is invented.

## Cache markers at this pin

`anthropic_prompt_cache_policy` for `api_mode=anthropic_messages` and a
Claude model on the cell proxy URL returns `(True, True)`. The default TTL
is 5 minutes (`{"type": "ephemeral"}`, no `ttl: 1h`). The proxy forwards
`cache_control`. A third-party base URL (the cell proxy is not
`anthropic.com`) strips replayed thinking blocks; system breakpoints are
still applied. Title calls are tool-less one-shots, so Hermes skips markers
on them. A title `cache_read` of 0 does not fail check 2.

Call 2 reading 0 while a later main call reads call 1's prefix is the
global-endpoint region split, not a missing marker. Making call 2 hit on
every cell would mean a regional endpoint for every arm. That is not done
here.
