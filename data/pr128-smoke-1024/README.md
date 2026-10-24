# PR #128 live smoke (2026-10-24, VM thesis-h1-cpu, branch cursor/vertex-proxy-harness-endpoints-8133 @ 80092845f)

- `api.log` / `api/`: proxy started via `start_from_env`, Vertex `claude-sonnet-5-5`.
  Anthropic `/v1/messages` non-stream + stream, OpenAI `/v1/chat/completions` non-stream + stream: all 200, all returned `PONG`.
  Tagging: header `main` → main, header `side:title` → side/title, no header short call → side/`heuristic:short-no-tools`.
  `<cell>.totals.json`: all=2 calls, main=1 call per cell, sums correct.
- `cell/`: stock OpenCode PR 13331, polyglot-rust-c, 1 trial per side, Sonnet, through the proxy (run_ab, cap $4).
  Both cells ran end to end (checker_exit 1, task not solved). 4 requests each, all `main` (`heuristic:main`).
  totals.json matches cell `requests_*` exactly. Cost $0.164 + $0.121. Transcripts left on VM.
