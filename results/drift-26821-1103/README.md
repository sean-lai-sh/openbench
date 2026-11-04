# drift rerun 26821 (opus, pin 3.0.71), 2026-11-03

- Host: **thesis-h1-cpu-3**. Both arms ran on this VM in one container. All 180 rows record vm_name thesis-h1-cpu-3, with no pooling across VMs.
- Code: main `00d9d9f9c171dc899228245c86fd855c1df4079a`. Image: `h2-env:1022@sha256:72c59033…`.
- Spend stop $300. Rerun-from `/h2/h2-hardsuite-1022/opus`. Ran 19:24 to 22:16 EST and finished normally (exit 0, no STOPPED file).
- Pin check: rev2 "pin ok: pr=26821 model=opus pin=3.0.71". The binaries (with 548648a3…, without 4643e131…) match the sha256s in the #238 gate.
- Load-proof gate: all 180 rows have embedded_version 3.0.71 and load_proof pass.
- **Cells: 180** (90 per arm, 9 tasks × 10 trials).
- **Spend: $90.9697** by row proxy cost (with $43.2692, without $47.7005). The driver's last spend.log sample was $89.4972 at 22:15, one minute before the end.
- 1 env_failure: without / video-processing timed out with cause checker_timeout.
- No file is over 50 MB, so there is no MANIFEST. The directory is 731 MB.

## Solves (out of 10 per task)
| Task | with | without |
|---|---|---|
| dna-insert | 0 | 0 |
| filter-js-from-html | 5 | 6 |
| model-extraction-relu-logits | 9 | 9 |
| polyglot-rust-c | 1 | 0 |
| regex-chess | 2 | 1 |
| sam-cell-seg | 0 | 0 |
| torch-pipeline-parallelism | 9 | 4 |
| torch-tensor-parallelism | 10 | 10 |
| video-processing | 3 | 4 |
| **Total** | **39/90** | **34/90** |
