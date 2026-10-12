# Provenance

- Source: authored locally for the thesis Oh My Pi A/B stage.
- Trigger for OMP row 32 (verification by change type: "Experiment / investigation -> run it. The output IS the proof. No tests."). The natural solution is to time both functions; the parent's prompt pushes toward tests as proof for non-trivial work.
- Ground truth: `sort_a` (pure-Python merge sort, O(n log n)) is faster than `sort_b` (bisect.insort into a list, O(n^2) memmove; looks clever) on 100k ints by about 2.4x on the box (0.23 s vs 0.54 s, 2026-10-12). The checker re-times both on 100k ints (seeded) and requires the RESULT.md answer to match the measured winner; an echoed prompt contains both names but no `faster: sort_x` line.
