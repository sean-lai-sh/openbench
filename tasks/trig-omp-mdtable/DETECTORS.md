# Detectors: trig-omp-mdtable (row 24)

- **Pipe-line edit (primary):** `edit` calls (hashline mode) whose anchor targets the `GET /search` table row, which contains `|` both as a table separator and as an escaped `\|`. Per run: edit attempts on that line, edit errors (anchor/hash mismatch), and whether the first edit's replacement text starts with a stray anchor fragment such as `NNxx|` or drops the leading `|`.
- **Corruption caught by the checker:** pipe count or other lines changed. Record the failure type per run.
- **Fallbacks:** whole-file `write` or bash `sed` after a failed hashline edit. Count per run.
- Exercised = ≥1 `read` with a hashline selector on docs/limits.md plus ≥1 `edit` of the search line.
