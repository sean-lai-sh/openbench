# Provenance

- Source: authored locally for OpenBench (original task, not imported).
- Trigger task: C# workspace for the OpenCode harness A/B rerun (PR 23771).
- `Program.cs` has two independent syntax errors, a missing `;` and a missing `)`, more than 15 lines apart. Roslyn reports syntax errors such as CS1002 about a second after open, and only when asked. It does not report semantic errors such as CS0103 for a loose file, so an undefined name never fires the LSP.
- The prompt does not mention LSP, diagnostics, or a replacement value. The cell does not run `dotnet restore` before the agent.
- Oracle: `dotnet build` must exit 0. The checker looks for `dotnet` on `PATH`, then `$DOTNET_ROOT`, then `/home/box/.dotnet/dotnet`. A missing SDK exits 2 so the cell is infra, not a wrong answer. There is no source-text fallback.
