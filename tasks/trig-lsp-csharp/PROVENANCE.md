# Provenance

- Source: authored locally for OpenBench (original task, not imported).
- Trigger task: C# workspace for the OpenCode harness A/B rerun (PR 23771).
- `Program.cs` references undefined `missingPort`. The merge build can surface that through Roslyn pull diagnostics; the parent cannot.
- A cell can install `roslyn-language-server` only when `dotnet` on PATH (or `DOTNET_ROOT`) is the .NET 10 SDK or newer. The provisioner installs with `--tool-path` into `$XDG_DATA_HOME/opencode/bin` and prepends that directory. Without SDK 10 the cell fails closed and does not run.
- Oracle: checker.sh runs `dotnet build` when the SDK can target `net10.0`. Otherwise it checks that `missingPort` is gone and `8417` is present, so CI can validate without the SDK.
