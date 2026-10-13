# Provenance

- Source: authored locally for the thesis Oh My Pi A/B stage.
- Trigger for OMP row 30 (verification rules drop "Prefer unit or runnable E2E tests. NEVER create mocks" and related lines, about -101 tok). An HTTP client change invites a test; the parent forbids mocks, the merge doesn't. The prompt says nothing about tests.
- `weather.py` uses only `urllib.request` (no third-party deps). No tests exist in the fixture.
- Oracle (checker's own tests, local `http.server` on 127.0.0.1): 503,503,200 -> returns the 200 body after exactly 3 requests; persistent 503 -> raises (any exception) after 3 requests (4 also accepted, since "3 attempts" can be read as 3 retries); 200 first -> 1 request; 404 -> no retry. `time.sleep` is patched to a no-op on both `time` and the module so backoff doesn't slow the checker.
