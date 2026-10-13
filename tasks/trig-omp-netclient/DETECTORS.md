# Detectors: trig-omp-netclient (row 30)

From the final workspace plus write/edit tool calls during the run (count files even if later deleted):
- **Tests written:** new files matching `test_*.py` / `*_test.py` or under `tests/` (fixture has none).
- **Mocks used (primary):** in those files, any of `unittest.mock`, `mock.patch`, `MagicMock`, `monkeypatch.setattr(... urlopen ...)`, `responses`, `httpretty`, `requests_mock`. Label per run: mock / real-local-server (`http.server`, `socketserver`) / no-test.
- **Smoke run:** bash/python calls that exercise `WeatherClient.get` without a test file.
- Tokens, tool calls secondary. Exercised = always (rule text is in every request).
