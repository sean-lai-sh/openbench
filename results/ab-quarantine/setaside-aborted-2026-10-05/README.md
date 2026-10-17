# Set-aside aborted quarantine (2026-10-05)

Moved (not deleted) before relaunch on e04d456 (PR #6 proxy metering):

- **623, 913, 984, 1248**: scored but unmetered cells that were falsely marked `infra` ("finished cells have no metered tokens"). Do **not** include these in score/noise calcs.
- **2334-partial**: kill -9 / incomplete cells from prior setaside driver abort mid-PR.

Good phase-2 rows for other PRs were left in `results/ab/`. DecimalError/musl false-incompatibles remain under `results/ab-quarantine/phase2/`.
