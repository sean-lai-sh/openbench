# Provider SDK pins and signature-400 rows

## signature-400 rows stay scored (Researcher ruling)

`failure_class=infra` rows whose error is the Anthropic 400
``Invalid `signature` in `thinking` block`` (`invalid_request_error`,
`messages.N.content.M`) are scored agent fails with
`failure_subclass=thinking_signature_replay`, so the write-up can report
them separately. Request bodies were not logged for these cells, so the
classification rests on transcripts (one cell per task was traced: OpenCode
replayed a signed thinking block out of order). A row leaves this bucket only
when `request_mangled=true` records a trace showing the proxy or SDK changed
the request. Every other adapter-infra row stays an unscored env failure.

Pinned `@ai-sdk/anthropic` is now pre-installed by
`thesis/ab/provision_provider_pins.py` into `~/h1/opencode-src/provider-pins/<version>/`
(read-only, sha256 `manifest.json`) and copied into each cell with no network.
A missing or wrong version fails before the agent runs with
`env_cause=provider_sdk_drift`. Every row records `installed_anthropic`.
