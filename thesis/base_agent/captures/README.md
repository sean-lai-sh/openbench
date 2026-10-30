# Real-harness captures for the AC3 build check

One directory per harness config, holding the real harness's requests as seen
at a loopback stub that stands where the counting proxy stands. The stub
answers with a canned end_turn, so no model is called. `obench.tests.test_stage4_build_gate`
requires a capture for every harness config and fails until one is committed.

```
captures/<config>/real.requests.jsonl   # one {method, path, headers, body} per line
captures/<config>/capture.toml          # provenance, read by the gate
```

`capture.toml`:

```toml
harness = "opencode"
harness_pin = "c10134729dd2ce00beb18604ec91f10319f59a78"  # must equal the config's harness_pin
binary_sha256 = "..."              # the binary that produced the capture
model = "claude-opus-5-5"          # the model id the harness was given
instruction = "Reply with ok."     # the prompt the harness was given
workdir = "/tmp/stub-ready-xyz"    # the cwd the harness ran in (cancels cwd bytes)
method = "thesis.ab.step8_stub_ready --capture"
captured_at = "2026-10-30"
captured_on = "<host>"
```

To produce one, see "Build check (AC3)" in `../README.md`. Captures come only
from the pinned open-source harness binaries. Never derive a config's text
from a capture of any closed-source harness.
