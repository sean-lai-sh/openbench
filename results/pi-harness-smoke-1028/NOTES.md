# Pi harness one-cell smoke — 2026-10-28 (PR #134)

Runner: GCP VM thesis-h1-cpu, image `h1-env:1027-strace`, Vertex ADC via metadata
(project nyu-rdg-fy26-js11531-a68d, location global). Model: claude-sonnet-5-5 only.
Route: Pi models.json baseUrl → per-cell obench proxy → Vertex (ledger `upstream_model: claude-sonnet-5-5`, 3 calls).
Egress: api.anthropic.com blocked on host, IP and container (`egress_verify.txt` each attempt). Spend cap $5 (monitor kill at $4.50).

| attempt | #134 SHA | result | cost |
|---|---|---|---|
| 1935 UTC | 73a846d2 | Pi build failed: TS2322 (stale `{}` catalog stubs) | $0 |
| 1941 UTC | 43b76ba4 | build OK; Vertex 400 `thinking.type.enabled` unsupported → infra, 0 calls | $0 |
| 1957 UTC | 64db7a2d | **completed=true**, failure_class=wrong_answer (checker exit 1), 3 calls, 2497 tokens | $0.0459 |

Fixes on #134: hydrate `src/providers/data` from published pi-ai tarball (d7aff22f, 73a846d2);
`--models` subset (2ca12e0f); models.json `compat.forceAdaptiveThinking` etc. matching pi-ai's built-in 5-5 entries (64db7a2d).
Harness smoke passes end-to-end; the wrong_answer is the task outcome, not a harness fault. Transcripts are under each attempt's `transcripts/`.
