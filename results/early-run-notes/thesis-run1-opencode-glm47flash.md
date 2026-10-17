# OpenBench hard tasks: OpenCode + GLM-4.7-Flash on GCP (Run 1)

**Date:** September 30, 2026 (runs 19:58–20:27 ET)
**Harness:** OpenCode 1.18.3 (pinned to the version in OpenBench's Dockerfile, `version_drift=false`)
**Model:** `unsloth/GLM-4.7-Flash-FP8-Dynamic` (FP8 build of `zai-org/GLM-4.7-Flash`, 31B), self-hosted
**Serving:** vLLM 0.30.0, tensor-parallel 2, tool parser `glm47`, reasoning parser `glm45`, 32,768-token context
**Hardware:** GCP `g2-standard-24` (2× NVIDIA L4, 24 GB each), `us-central1-c`, ~15.5 GiB of weights per GPU
**Benchmark:** OpenBench (fork: github.com/sean-lai-sh/openbench), the 3 hard tasks, `obench legacy run --exec local`, 1 trial per task, 7200 s timeout
**Inference:** entirely on GCP, with no outside model APIs

## Results

| Task | Result | Score | Checker output | Agent time | Turns | Total tokens | Output tokens (reasoning) |
|---|---|---|---|---|---|---|---|
| make-ci-green | Pass | 1.00 | 16/16 tests passing | 69.5 s | 16 | 189,625 | 3,161 (1,689) |
| add-feature | Fail (wrong answer) | 0.60 | feature 2/6, regression 4/4 | 1,048.3 s | 169 | 2,852,358 | 45,685 (22,753) |
| misleading-error | Pass | 1.00 | expected line printed | 22.0 s | 7 | 57,020 | 655 (386) |

**Pass rate:** 2/3. **Mean score:** 0.87. **Total agent time:** about 19 min. **Compute:** about 1.1 VM-hours (about 2.2 L4 GPU-hours, about $2.25).

### add-feature failure detail
All four `@include` feature tests failed: basic include, nested include, include relative to the including file, and override after include. All 4 regression groups still passed, so existing behavior wasn't broken. The model also left `DEBUG PARSER:` print statements in the parser. It took 169 turns and 2.85M tokens, about 15× more than the other two tasks combined, which suggests it went in circles instead of converging.

## Caveats
- One trial per task (n=1). These are point observations, not stable estimates, so repeated trials are needed before comparing with other harness and model pairs.
- FP8-quantized weights were used to fit on 2× L4. Scores may differ from the BF16 model.
- No prompt caching on the self-hosted server (cache-read tokens = 0), so the token counts are all uncached input.
- One earlier attempt was discarded because of a config error. OpenCode requested `max_tokens=32000`, which vLLM rejected, so the agent never ran. Those rows are kept separately and excluded.

## Setup notes (lessons from the first deploy)
1. The NYU GCP project has no `default` network and bans external IPs by org policy, so the VM runs on a dedicated `thesis-vpc` with Cloud NAT.
2. L4 capacity ran out in `us-central1-a` and `-b`; `-c` worked.
3. OpenCode's system prompt alone is about 7.2k tokens and turns reached about 14.6k, so an 8k context is too small and 32k is used.
4. OpenCode needs an explicit model context and output limit for self-hosted models.
5. vLLM needs tool calling on (`--enable-auto-tool-choice` plus the GLM-4.7 parser), because OpenCode edits files through tool calls.
6. Everything is created and torn down by scripts in `thesis/gcp/`, and only touches `thesis-`-named resources in the shared project.

## Next steps
- Run 3+ trials per task for variance.
- Compare against OpenBench's published OpenCode and Pi rows and other models under the same harness.
- Vary the harness with the model held fixed, which is the thesis's core experiment.
