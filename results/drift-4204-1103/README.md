# drift rerun 4204 (opus, pin 2.0.0), 2026-11-03/04

- Host: **thesis-h1-cpu-2**. Both arms ran on this VM in one container. All 180 rows record host `thesis-h1-cpu-2.c.nyu-rdg-fy26-js11531-a68d.internal`. No pooling across VMs.
- Code: `00d9d9f9c171dc899228245c86fd855c1df4079a`. Image: `h2-env:1022@sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff`. Instance id `2940849335632108188`.
- Spend stop $300. Spec: `opus 4204 2.0.0 /h2/h2-hardsuite-1022/opus`. Ran 2026-11-03 19:23:31 EST to 2026-11-04 05:17:49 EST and finished normally (exit 0, no STOPPED file).
- Pin check: rev2 "pin ok: pr=4204 model=opus pin=2.0.0". Load-proof: all 180 rows have `load_proof=pass`. `embedded_version` is null on every row (SDK 2.0.0 sends no UA suffix; proof is not from user-agent). `version_drift` is true on every row (custom CLI vs Dockerfile pin; waived at launch).
- **Cells: 180** (90 per arm, 9 tasks × 10 trials). The last spend.log sample was 179 cells / $89.1388 at 05:16:48 EST; the 180th cell is in the jsonl.
- **Spend: $89.5488** by row `requests_cost_usd` (with $45.6064, without $43.9424). Under the $120-before-180 and $0.90/cell-after-30 alerts (mean ≈ $0.50/cell).
- Infra: with/sam-cell-seg trials 1, 3, 5; without/sam-cell-seg trials 3, 4, 5, 7 (7 cells).
- 1 env_failure: without / model-extraction-relu-logits trial 9, `env_cause=checker_timeout` (`failure_class=timeout`).
- Three workspace tarballs are over 50 MB and are listed in `MANIFEST-large-files.txt` (not in git). Full archive: thesis-h1-cpu-2 `~/h2/drift-4204-1103` and box `/workspace/d4204.tgz` (sha256 `a743c0e376c9c1a0f40dc28d8992022e73bbbdb73d1e528e2a42a62c7a634504`). Directory in this PR is 308 MB.

## Solves (out of 10 per task)

| Task | with | without |
|---|---|---|
| dna-insert | 0 | 0 |
| filter-js-from-html | 5 | 4 |
| model-extraction-relu-logits | 10 | 9 |
| polyglot-rust-c | 4 | 3 |
| regex-chess | 10 | 10 |
| sam-cell-seg | 0 | 0 |
| torch-pipeline-parallelism | 9 | 7 |
| torch-tensor-parallelism | 10 | 10 |
| video-processing | 0 | 0 |
| **Total** | **48/90** | **43/90** |
