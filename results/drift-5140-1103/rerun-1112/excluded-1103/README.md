# Excluded: 2026-11-03 partial cells (not in any tally)

These 9 cells (4 with, 5 without; `ended_et` 2026-11-03) came from the partial #239 run that the disk guard stopped. The 11/12 resume skipped them instead of rerunning them, so they had been mixed into `../opus/5140/`. They were moved here on 2026-11-13 and are **excluded from all tallies** (with 1/4 solved, without 2/5 solved). The 9 slots were rerun on 2026-11-13 with the same head, pin, image and `cell.sh`; those reruns are in `../opus/5140/`.

Contents: `opus/5140/cells/`, `opus/5140/transcripts/` (scrubbed), `opus/5140/{with,without}.jsonl` (projected from these cells), `opus/proxy-ledger/` (the 13 ledger triples dated 2026-11-03), and `MANIFEST.txt` (workspace tarballs, size + sha256, kept on VM `thesis-h1-cpu` under `~/h2/drift-5140-1103/excluded-1103/opus`).
