# Provenance

- Source: authored locally for OpenBench (original task, not imported).
- Trigger task: webfetch an image for the OpenCode harness A/B rerun (PR 13331).
- The instruction token `__OBENCH_WEBFETCH_URL__` is replaced, when the cell's options are `webfetch=local`, with `http://127.0.0.1:<port>/color.png`. The runner serves a one-pixel red PNG as `Content-Type: image/png` and does not call a public host.
- Oracle: checker.sh requires answer.txt to be the word `red`.
