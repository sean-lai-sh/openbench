# Provenance

- Source: authored locally for OpenBench (original task, not imported).
- Trigger task: new workspace with spec.png for the OpenCode harness A/B rerun (PR 3052).
- The map option `modalities=image` sets that cell's `claude-opus-5-5` entry to `modalities.input` including `image` (and `output: ["text"]`, which the schema requires). The read tool then attaches spec.png instead of taking the text-only error branch.
- Oracle: checker.sh imports config and checks PORT.
