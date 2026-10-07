# Provenance

- Source: authored locally for OpenBench (original task, not imported).
- Trigger task: TypeScript workspace for the OpenCode harness A/B rerun (PR 2334).
- node_modules/typescript is installed into the cell workspace by the runner, not committed.
- Oracle: checker.sh. With typescript installed it runs tsc --noEmit. Otherwise it checks the string assignment so CI can validate without node.
