# Detectors: trig-omp-multiedit (row 20)

From the session's tool calls/results for the `edit` tool (hashline mode):
- **Tag mismatch errors:** edit tool results containing `>>>` mismatch markers (the hashline "tag mismatch" error; match the error text, not the model's own message).
- **No-op errors:** edit results reporting the replacement is `identical`.
- **Edit calls per file:** number of `edit` calls with path `handlers.py`; the prompt rule is one call per file with all ops. Also count `read` calls on handlers.py between edits (re-reads).
- **Ops per call:** length of `edits[]` in each edit call.
- **Fallbacks:** `write` calls rewriting handlers.py wholesale (count separately; they bypass hashline).
- **Exercised:** ≥1 hashline `edit` call on handlers.py. Confirm edit mode by the edit tool's description in request #1 (contains `LINE#ID`).
