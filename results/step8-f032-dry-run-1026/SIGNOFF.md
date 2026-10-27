**Researcher ruling: F03-2 signed off, with conditions**

- **Controls pass.** Bun stamps the build time into each binary, so byte-identical builds aren't required. A rebuild counts as equivalent when its source commit matches and `--version` matches apart from the timestamp.
- **Missing old lockfiles don't block.** D4 pins the provider version, and the runtime probe checks it.
- **The provider check runs inside the batch through the #156 probe, not as a separate smoke.**
  - The first cell of each of the 22 sides launches first. If a first cell loads a provider version that differs from its pin, that side stops, its cells are marked infra, and it gets fixed before it runs again.
  - If more than 2 sides mismatch, the whole batch stops and goes back to the Researcher.
  - Every later cell is also checked against its pin. A mismatch counts as infra and is rerun.
- **Scoring:** the Researcher scores F03-2 after the batch finishes, with the probe column included.
