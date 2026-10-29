# Harness comparison: amendment A3 (2026-10-29)

Amends `harness-comparison-prereg.md` (Stage 3). Written 2026-10-29 and committed before the Pi vs OpenCode batch launch. No batch cell has been scored.

Anything not changed here inherits the pre-registration, including amendments A1 and A2.

## What was seen at the time

The batch is on hold. Two gate cells on `polyglot-rust-c` (one Pi, one OpenCode; `results/pi-oc-gate-1029`) have already been scored. Both primary scores are 0. In both, the checker failed because `/app/polyglot` contained `main`, `cmain`, and `main.rs`, not `main.rs` alone. Those gate cells are not batch data and are not analysed as a comparison.

## Amendment A3 (2026-10-29, before the batch launch)

1. **Primary score unchanged.** Pass/fail, the cell `score`, and the comparisons in §§9–10 and amendments A1 and A2 stay on the existing checker. This amendment does not drop, replace, or reweight that score.

2. **Secondary result `functional_pass`, for `polyglot-rust-c` only.** It is the same checker run inside the task image, skipping only the check that `/app/polyglot` contains only `main.rs`. Every other check is kept (both compilers, and the Fibonacci cases). For every other task, `functional_pass` is null.

3. **Computed from the saved workspace.** No extra agent runs. The field is filled from the workspace the cell already produced.

4. **Leftover files.** If primary differences are mostly due to leftover files, that is reported as a finding. It does not change the primary score.
