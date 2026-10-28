# PR #134 bridge smoke, head 1edba44a04e93b6c3c04e3081bc6b937646f3ae0 (2026-10-28, VM thesis-h1-cpu)

Image h1-env:1027-strace (sha256:2506cd37...), Vertex model claude-sonnet-5-5. OpenCode sha ba54cee55e18b47fb70badc84ae2cbac7c83d258, Node 20.19.2.
The VM can't reach github.com, so the head was shipped from the box as a git bundle and checked out detached in ~/ob-pr134.

## Unit tests (attempt1-file-adc/pr134c-unittest.out)
test_proxy_bridge + test_cell_imports: 17 tests, OK.

## Attempt 1 (exact repeat of the 1028b command): both cells reach the proxy, upstream auth fails
- Pi ae05ee44e4866c99: bridge; egress blocked (sinkhole 0.0.0.0); reached=yes calls=0; infra. proxy_observed [].
- OpenCode 389cfae596241f9b: bridge; egress blocked; reached=yes calls=0; wrong_answer (agent errored on its first request). proxy_observed [].
- Cause: the proxy returned 400 "No such file or directory: ~/.config/gcloud/application_default_credentials.json".
  thesis/ab/vertex_anthropic_proxy.py:793-808: _fetch reads the ADC file unless OBENCH_ADC_METADATA=1, and the VM
  has only its compute service account. This was an env/setup gap. The in-cell import fixes worked. $0.

## Attempt 2 (same command plus OBENCH_ADC_METADATA=1)
| | Pi f13363d84726bdb8 | OpenCode 362e87ae1e9a8384 |
|---|---|---|
| network_mode | bridge (172.17.0.1:45135) | bridge |
| egress | api.anthropic.com blocked (blocked sinkhole 0.0.0.0) | same |
| proxy-reached | reached=yes calls=2 | reached=yes calls=4 |
| proxy_observed | 2x thinking_mode default, thinking_sent adaptive | 4x thinking_mode default, thinking_sent none |
| tokens (ledger) | cache_write 7105, in 6, out 2055 | cache_write 49813, in 12, out 3956 |
| spend | $0.0383 | requests_cost_usd reported 0.0; about $0.25 at Sonnet list rates |
| outcome | completed, wrong_answer (checker_exit 1) | completed, wrong_answer (checker_exit 1) |

Combined spend was about $0.29, under the $2 cap.
