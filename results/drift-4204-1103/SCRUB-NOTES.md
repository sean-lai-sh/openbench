# Scrub notes — drift-4204-1103

Transcripts and OpenCode session files under `opus/4204/transcripts/` were replaced in place with copies produced by `obench/scrub.py` (same rules as `scrub_text` / `python3 obench/scrub.py <src> --out <dir>`). Filenames and the directory layout are unchanged, so scored-row paths and README references still resolve. Nothing under this tree was removed.

Originals of those files stay off-repo: `thesis-h1-cpu-2:~/h2/drift-4204-1103` and the archive whose sha256 is already recorded in `MANIFEST-large-files.txt`.

Scored rows (`opus/4204/cells/`, `opus/4204/with.jsonl`, `opus/4204/without.jsonl`), `spend.log`, README solve counts and spend figures, `MANIFEST-large-files.txt`, and `driver.log` were not modified. They hold commit ids, sha256 digests, and, in row `cmd` text, chess FEN strings. The scrubber treats 32+ hex digits and 40+ base64-shaped tokens as PII, so running it on those files would rewrite the result rows.

## What changed

- Scrubbed (bytes changed): **1634** files
  - 180 arm transcripts `opencode_*_trialN.txt`
  - 180 `agent-output.txt`
  - 4 `final-answer.txt`
  - 1266 `storage/part/**/*.json`
  - 4 `storage/message/**/*.json`
- Already clean, left as committed: **6986** files (session metadata, probes, migration markers, and the rest of `storage/message`)
- Removed: **0**

Replacements were only `hex-blob` (555) and `base64-blob` (10952). No email, key, home-path, username, or hostname hits were present.

The arm transcripts still had the runner banner `LOCAL-ONLY -- unscrubbed`. `scrub.py` does not treat that sentence as PII, so after scrubbing it was rewritten to say the file was scrubbed with `obench/scrub.py` and that the unscrubbed original is off-repo. That banner edit is the only change beyond `scrub_text`.

## Checks

Transcript and session tree (the files this pass was allowed to rewrite):

```
$ python3 obench/scrub.py results/drift-4204-1103/opus/4204/transcripts --check
CLEAN: no potential PII found under results/drift-4204-1103/opus/4204/transcripts
```

Exit code 0.

Whole dataset directory, including the result rows this pass was not allowed to rewrite:

```
$ python3 obench/scrub.py results/drift-4204-1103 --check
TOTAL: 35504 potential hit(s) across 185 file(s).
```

Exit code 1. Every remaining hit is in an untouched file:

- 180 files under `opus/4204/cells/`
- `opus/4204/with.jsonl`
- `opus/4204/without.jsonl`
- `README.md`
- `MANIFEST-large-files.txt`
- `driver.log`

`spend.log` and `opus/proxy-ledger/` report no hits and were not modified.
