# Provenance

- Source: authored locally for the thesis Oh My Pi A/B stage.
- Trigger for OMP row 36 ("User-reported state is ground truth... NEVER re-run checks to confirm what the user already reported", about +67 tok). The user reports the exact failing test and error, so the merge build should act directly; the parent typically reproduces first.
- `conftest.py` has a session fixture that sleeps 8 s (simulates a slow DB fixture), so re-running costs wall time without changing correctness.
- Bug: `parse_date` uses `strptime(s, "%Y-%m-%dT%H:%M:%S")`, so a trailing `Z` breaks it. Fix: accept `Z` (and keep naive inputs working), returning UTC-aware datetimes for `Z` inputs.
- Oracle: checker's own tests (no slow conftest) for parse_date and an untouched helper.
