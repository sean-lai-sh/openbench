# drift rerun 5140 (opus, pin 2.0.50), 2026-11-03: stopped by the disk guard, no drift conclusion

- Code `b1cbded32a92eb08c107428dc46a1b015ce777c4`, image `h2-env:1022@sha256:72c59033…`, on thesis-h1-cpu. The spend stop was $300.
- Started 17:53:48 EST. The driver's **disk guard** stopped it at 18:30:36 EST with 13 GB free, killing the container (exit 137).
- **Incomplete:** 9 cells finished (4 with, 5 without). With-side regex-chess and the rest of the hard suite never ran.
- Spend: **$4.6502** (with $1.5661, without $3.0841).
- Every row has embedded_version 2.0.50 and load_proof pass.
- No file is over 50 MB, so there is no MANIFEST. The directory is 9.2 MB.

| Task | with | without |
|---|---|---|
| dna-insert | no (wrong answer) $0.181 | no (wrong answer) $0.109 |
| filter-js-from-html | **yes** $0.734 | no (wrong answer) $0.985 |
| model-extraction-relu-logits | no (timeout) $0.386 | **yes** $0.232 |
| polyglot-rust-c | no (wrong answer) $0.265 | no (wrong answer) $0.147 |
| regex-chess | did not run | **yes** $1.611 |

Solves: with 1/4, without 3/5. **Stopped by the disk guard, no drift conclusion.** The Researcher's plan is to finish 5140 later on thesis-h1-cpu as a continuation of this PR.
