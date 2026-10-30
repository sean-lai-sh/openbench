# sdkpin-test-1030: #207 test pair (h2-hardsuite-1022 opus PR 4204 dna-insert t1)

Cleared by the PM and Researcher. Capped at $2; the spend counts toward the $300 stop.
Code: PR #207 head 50e4e4c419227c4d67ede8c9a450fc5273530ecf, mounted at /ob.

## Image
The batch used h2-env:1022 (sha256:72c59033194aae26f6de67c62c77d742aef1d71849000e308f3ee875ff5169ff).
Evidence:
- `results/h2-hardsuite-1022/driver.log`: both starts (17:21:48 and 17:37:49 as logged) record `image=h2-env:1022(sha256:72c5903…)` and runner 980e71b6.
- The original cell (started 2026-10-22 21:40:38 EDT, runner 980e71b6) falls inside the second start's window.
- The VM launcher `~/h2/h2.sh` (mtime Oct 22 21:37) runs `h2-env:1022 /h2/run1.sh`, and `~/h2/run1.sh` says "inside h2-env:1022".
- The `driver/h2.sh` and `driver/run1.sh` committed later in the repo name h1-env:1022. That is a later rewrite and not what this batch ran.
- The row's own `image_digest` is null. The batch's launcher did not set `OBENCH_AGENT_IMAGE`, so the rerun's `cell_image` is null as well.

## How it was run
- The env and mounts are the same as `~/h2/h2.sh` `run()`: `--network host`, `OBENCH_ADC_METADATA=1`, `GOOGLE_CLOUD_PROJECT`, `VERTEX_LOCATION=global`, `OBENCH_VM_TYPE`, `TZ`, and mounts for /ob, /h1 and /h2.
- The run_ab flags are the same as `/h2/run1.sh`, except `--tasks dna-insert --trials 1 --jobs 1 --max-cost-usd 2`.
- One addition: `OBENCH_PROVIDER_PIN_ROOT=/h1/opencode-src/provider-pins`, because `~` inside the container is /root.

## Pin store
- `provision_provider_pins.py 2.0.0` was run as root, because `provider-pins/` is root-owned. It used bun 1.2.14 and printed `ok (installed)`.
- `--verify 2.0.0` printed `@ai-sdk/anthropic@2.0.0: ok`, exit 0.
- tree_sha256 is bee284c2…, with 1051 files.

## Result: FAIL against the pass rule
| side | provider_versions / toolchain anthropic | installed_anthropic | env_failure / class | solved | cost | agent s |
|---|---|---|---|---|---|---|
| without | 2.0.0 / 2.0.0 | null | False / wrong_answer | no | $0.177299 | 7.985 |
| with | 2.0.0 / 2.0.0 | null | False / wrong_answer | no | $0.177269 | 8.998 |

- "Unhandled chunk type" appears nowhere in the outputs (`grep -r`, rc 1).
- **Traces are not full.** On both sides the agent made one tool call. The next request then returned 200 with 0 output tokens, step-finish was `reason: "unknown"`, and OpenCode exited about 9 s in. The row sets `suspect_startup_exit=true` and `final_answer_present=false`.
- **The `installed_anthropic` column is null on both rows.** It is only filled on the `obench/run.py` row path. run_ab cell rows don't carry it, which is a #207 gap. The version is still on the rows, as `provider_versions`, `provider_manifest_version` and `toolchain.anthropic`.
- The transcripts also show `@opencode-ai/plugin@0.0.0--202610170212 failed to resolve` at startup.
- Total cost: $0.354568.
