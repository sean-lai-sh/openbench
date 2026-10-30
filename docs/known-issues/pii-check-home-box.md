On the thesis-h1-cpu VM, `python3 -m unittest discover` at dd0eb6cb (and at 57e78747a) gives 1 failure and 84 errors. `publish.create_bundle` raises `PublishError: PII sanity check found 2 potential hit(s)…` because test bundles contain the host path `/home/box/...`.

Affected modules:
- `obench.tests.test_site` (most of them)
- `obench.tests.test_leaderboard`
- `obench.tests.test_community`
- `obench.tests.test_publish` (`test_cli_publish_and_verify_e2e` is the failure)
- `obench.tests.test_report_page`
- `obench.tests.test_adapter_timeout` (`test_opencode`)
- `obench.tests.test_provider_pin` (`CellAbortTests`)

The counts are the same before and after #191, so #191 didn't cause them.

Fix: build test bundles with a neutral temp path, or make the PII check allow the test-fixture root.
