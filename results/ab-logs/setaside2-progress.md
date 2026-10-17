# Set-aside 17 progress (round 2 @ e04d456 / PR #6)

Cap soft: cumulative est. spend pause around $800–1000 (driver CAP=900, HEADROOM=40). Prior spend ~$414; phase for 17 ~$350–400. Smoke #17098 A/A passed first.




## PR 623 (exit 0, ~15:34 ET)
- PR 623: pass 1.000→1.000; wall 41.2→43.2s (+4.8%); turns n/a→n/a; tok 181k→191k (+5.5%); cost $0.219→$0.199 (-9.3%); PR $10.04; noise_floor=within; SDK without[bun=1.2.14,ai=4.3.16,anthropic=1.2.12] with[bun=1.2.14,ai=4.3.16,anthropic=1.2.12]
- without: n=24 pass=1.000 wall=41.2s turns=n/a tok/cell=180730 cost/cell=$0.219
- without toolchain: bun=1.2.14,ai=4.3.16,anthropic=1.2.12
- with: n=24 pass=1.000 wall=43.2s turns=n/a tok/cell=190653 cost/cell=$0.199
- with toolchain: bun=1.2.14,ai=4.3.16,anthropic=1.2.12
- cumulative spend (all phases, est.): $426.09
## PR 913 (exit 0, 15:35 ET)
- PR 913: without: incompatible (preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m> Reply with ok) | with: incompatible (preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m> Reply with ok); SDK without[bun=1.2.14,ai=5.0.0-beta.7,anthropic=2.0.0-beta.11] with[bun=1.2.14,ai=5.0.0-beta.7,anthropic=2.0.0-beta.11]
- without: incompatible — preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m> Reply with ok
- without toolchain: bun=1.2.14,ai=5.0.0-beta.7,anthropic=2.0.0-beta.11
- with: incompatible — preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m> Reply with ok
- with toolchain: bun=1.2.14,ai=5.0.0-beta.7,anthropic=2.0.0-beta.11
- cumulative spend (all phases, est.): $423.66
- SDK: without: bun=1.2.14, ai=5.0.0-beta.7, anthropic=2.0.0-beta.11; with: bun=1.2.14, ai=5.0.0-beta.7, anthropic=2.0.0-beta.11; sdk_changed=''

## PR 984 (exit 0, 15:35 ET)
- PR 984: without: incompatible (preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic) | with: incompatible (preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic); SDK without[bun=1.2.14,ai=5.0.0-beta.15,anthropic=2.0.0-beta.11] with[bun=1.2.14,ai=5.0.0-beta.15,anthropic=2.0.0-beta.11]
- without: incompatible — preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic
- without toolchain: bun=1.2.14,ai=5.0.0-beta.15,anthropic=2.0.0-beta.11
- with: incompatible — preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic
- with toolchain: bun=1.2.14,ai=5.0.0-beta.15,anthropic=2.0.0-beta.11
- cumulative spend (all phases, est.): $423.66
- SDK: without: bun=1.2.14, ai=5.0.0-beta.15, anthropic=2.0.0-beta.11; with: bun=1.2.14, ai=5.0.0-beta.15, anthropic=2.0.0-beta.11; sdk_changed=''

## PR 1248 (exit 0, 15:36 ET)
- PR 1248: without: incompatible (preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic) | with: incompatible (preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic); SDK without[bun=1.2.14,ai=5.0.0-beta.21,anthropic=2.0.0-beta.11] with[bun=1.2.14,ai=5.0.0-beta.21,anthropic=2.0.0-beta.11]
- without: incompatible — preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic
- without toolchain: bun=1.2.14,ai=5.0.0-beta.21,anthropic=2.0.0-beta.11
- with: incompatible — preflight exited before any metered call: exit 1: [0m █▀▀█ █▀▀█ █▀▀ █▀▀▄ [0m█▀▀ █▀▀█ █▀▀▄ █▀▀ █░░█ █░░█ █▀▀ █░░█ [0m█░░ █░░█ █░░█ █▀▀ ▀▀▀▀ █▀▀▀ ▀▀▀ ▀ ▀ [0m▀▀▀ ▀▀▀▀ ▀▀▀ ▀▀▀ [0m [1m@ [0manthropic
- with toolchain: bun=1.2.14,ai=5.0.0-beta.21,anthropic=2.0.0-beta.11
- cumulative spend (all phases, est.): $423.66
- SDK: without: bun=1.2.14, ai=5.0.0-beta.21, anthropic=2.0.0-beta.11; with: bun=1.2.14, ai=5.0.0-beta.21, anthropic=2.0.0-beta.11; sdk_changed=''
- SDK: without: bun=1.2.19, ai=5.0.8, anthropic=2.0.0; with: bun=1.2.19, ai=5.0.8, anthropic=2.0.0; sdk_changed=''

## PR 2367 (exit 0, 15:38 ET)
- PR 2367: pass 0.000→0.000; wall 4.8→4.6s (-3.7%); turns n/a→n/a; tok 16k→16k (+0.2%); cost $0.026→$0.026 (+2.1%); PR $1.24; noise_floor=within; SDK without[bun=1.2.19,ai=5.0.8,anthropic=2.0.0] with[bun=1.2.19,ai=5.0.8,anthropic=2.0.0]
- without: n=24 pass=0.000 wall=4.8s turns=n/a tok/cell=15744 cost/cell=$0.026
- without toolchain: bun=1.2.19,ai=5.0.8,anthropic=2.0.0
- with: n=24 pass=0.000 wall=4.6s turns=n/a tok/cell=15770 cost/cell=$0.026
- with toolchain: bun=1.2.19,ai=5.0.8,anthropic=2.0.0
- cumulative spend (all phases, est.): $426.72
- SDK: without: bun=1.2.19, ai=5.0.8, anthropic=2.0.0; with: bun=1.2.19, ai=5.0.8, anthropic=2.0.0; sdk_changed=''

## PR 3052 (exit 0, 15:39 ET)
- PR 3052: pass 0.000→0.000; wall 4.8→4.6s (-4.9%); turns n/a→n/a; tok 16k→16k (-0.0%); cost $0.050→$0.055 (+9.3%); PR $2.51; noise_floor=within; SDK without[bun=1.2.21,ai=5.0.8,anthropic=2.0.0] with[bun=1.2.21,ai=5.0.8,anthropic=2.0.0]
- without: n=24 pass=0.000 wall=4.8s turns=n/a tok/cell=16044 cost/cell=$0.050
- without toolchain: bun=1.2.21,ai=5.0.8,anthropic=2.0.0
- with: n=24 pass=0.000 wall=4.6s turns=n/a tok/cell=16043 cost/cell=$0.055
- with toolchain: bun=1.2.21,ai=5.0.8,anthropic=2.0.0
- cumulative spend (all phases, est.): $429.23
- SDK: without: bun=1.2.21, ai=5.0.8, anthropic=2.0.0; with: bun=1.2.21, ai=5.0.8, anthropic=2.0.0; sdk_changed=''

## PR 3115 (exit 0, 15:40 ET)
- PR 3115: pass 0.000→0.000; wall 4.8→4.8s (-0.7%); turns n/a→n/a; tok 16k→16k (+0.0%); cost $0.027→$0.046 (+68.4%); PR $1.75; noise_floor=CLEAR; SDK without[bun=1.3.0,ai=5.0.8,anthropic=2.0.0] with[bun=1.3.0,ai=5.0.8,anthropic=2.0.0]
- without: n=24 pass=0.000 wall=4.8s turns=n/a tok/cell=16063 cost/cell=$0.027
- without toolchain: bun=1.3.0,ai=5.0.8,anthropic=2.0.0
- with: n=24 pass=0.000 wall=4.8s turns=n/a tok/cell=16070 cost/cell=$0.046
- with toolchain: bun=1.3.0,ai=5.0.8,anthropic=2.0.0
- cumulative spend (all phases, est.): $430.98
- SDK: without: bun=1.3.0, ai=5.0.8, anthropic=2.0.0; with: bun=1.3.0, ai=5.0.8, anthropic=2.0.0; sdk_changed=''

## PR 3369 (exit 0, 15:40 ET)
- PR 3369: without: n=24 pass=0.000 wall=4.5s turns=n/a tok=16k cost=$0.024 UNMETERED=3 | with: incompatible (provider stream error with no metered tokens: {"type":"error","timestamp":1791229254084,"sessionID":"ses_ef26aaef5fferMtild3rUP4L94","error":{"name":"UnknownError","data":{"message":"Error: Unhandled ); SDK without[bun=1.3.0,ai=5.0.8,anthropic=2.0.0] with[bun=1.3.0,ai=5.0.8,anthropic=2.0.0]
- without: n=24 pass=0.000 wall=4.5s turns=n/a tok/cell=15928 cost/cell=$0.024
- without toolchain: bun=1.3.0,ai=5.0.8,anthropic=2.0.0
- with: incompatible — provider stream error with no metered tokens: {"type":"error","timestamp":1791229254084,"sessionID":"ses_ef26aaef5fferMtild3rUP4L94","error":{"name":"UnknownError","data":{"message":"Error: Unhandled 
- with toolchain: bun=1.3.0,ai=5.0.8,anthropic=2.0.0
- cumulative spend (all phases, est.): $431.66
- SDK: without: bun=1.3.0, ai=5.0.8, anthropic=2.0.0; with: bun=1.3.0, ai=5.0.8, anthropic=2.0.0; sdk_changed=''

## PR 3418 (exit 0, 15:41 ET)
- PR 3418: without: incompatible (provider stream error with no metered tokens: {"type":"error","timestamp":1791229269195,"sessionID":"ses_ef26a753affedpyRSGUa5EwH5X","error":{"name":"UnknownError","data":{"message":"Error: Unhandled ) | with: n=24 pass=0.000 wall=4.3s turns=n/a tok=16k cost=$0.027 UNMETERED=3; SDK without[bun=1.3.0,ai=5.0.8,anthropic=2.0.0] with[bun=1.3.0,ai=5.0.8,anthropic=2.0.0]
- without: incompatible — provider stream error with no metered tokens: {"type":"error","timestamp":1791229269195,"sessionID":"ses_ef26a753affedpyRSGUa5EwH5X","error":{"name":"UnknownError","data":{"message":"Error: Unhandled 
- without toolchain: bun=1.3.0,ai=5.0.8,anthropic=2.0.0
- with: n=24 pass=0.000 wall=4.3s turns=n/a tok/cell=15929 cost/cell=$0.027
- with toolchain: bun=1.3.0,ai=5.0.8,anthropic=2.0.0
- cumulative spend (all phases, est.): $432.34
- SDK: without: bun=1.3.0, ai=5.0.8, anthropic=2.0.0; with: bun=1.3.0, ai=5.0.8, anthropic=2.0.0; sdk_changed=''

## PR 4204 (exit 0, 15:42 ET)
- PR 4204: without: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/0d3d48bb5964a95e939edcea3bb726a21823d1a1/opencode') | with: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/963a926db24ea70f6002cde66d0ff858de06fae2/opencode'); SDK without[unknown] with[unknown]
- without: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/0d3d48bb5964a95e939edcea3bb726a21823d1a1/opencode'
- without toolchain: unknown
- with: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/963a926db24ea70f6002cde66d0ff858de06fae2/opencode'
- with toolchain: unknown
- cumulative spend (all phases, est.): $432.34
- SDK: without: (no toolchain); with: (no toolchain); sdk_changed=''

## PR 4838 (exit 0, 15:42 ET)
- PR 4838: without: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/ff609a52c13fa0444cb338d35fb16a07a820b539/opencode') | with: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/aaa31f02af5cd1d90e11549ee7b291e2f2a913d2/opencode'); SDK without[unknown] with[unknown]
- without: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/ff609a52c13fa0444cb338d35fb16a07a820b539/opencode'
- without toolchain: unknown
- with: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/aaa31f02af5cd1d90e11549ee7b291e2f2a913d2/opencode'
- with toolchain: unknown
- cumulative spend (all phases, est.): $432.34
- SDK: without: (no toolchain); with: (no toolchain); sdk_changed=''

## PR 2334 (exit 0, ~15:37 ET (backfill))
- PR 2334: pass 0.000→0.000; wall 5.5→4.6s (-16.0%); turns n/a→n/a; tok 16k→16k (-0.3%); cost $0.048→$0.028 (-41.1%); PR $1.81; noise_floor=CLEAR; SDK without[bun=1.2.19,ai=5.0.8,anthropic=2.0.0] with[bun=1.2.19,ai=5.0.8,anthropic=2.0.0]
- without: n=24 pass=0.000 wall=5.5s turns=n/a tok/cell=15800 cost/cell=$0.048
- without toolchain: bun=1.2.19,ai=5.0.8,anthropic=2.0.0
- with: n=24 pass=0.000 wall=4.6s turns=n/a tok/cell=15746 cost/cell=$0.028
- with toolchain: bun=1.2.19,ai=5.0.8,anthropic=2.0.0
- cumulative spend (all phases, est.): $432.34

## PR 5066 (exit 0, 15:43 ET)
- PR 5066: without: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/350a32274a24e6f5ca3ea30be114a8171a58270f/opencode') | with: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/a607f33552b653af5e7ab5233c2da3389b978e68/opencode'); SDK without[unknown] with[unknown]
- without: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/350a32274a24e6f5ca3ea30be114a8171a58270f/opencode'
- without toolchain: unknown
- with: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/a607f33552b653af5e7ab5233c2da3389b978e68/opencode'
- with toolchain: unknown
- cumulative spend (all phases, est.): $432.34
- SDK: without: (no toolchain); with: (no toolchain); sdk_changed=''

## PR 5131 (exit 0, 15:43 ET)
- PR 5131: without: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/40eb8b93e132daac1dff63e260cb61a880a2ba4d/opencode') | with: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/ba417d80b1174d0e289d8fc91c77a8f6a0d592f4/opencode'); SDK without[unknown] with[unknown]
- without: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/40eb8b93e132daac1dff63e260cb61a880a2ba4d/opencode'
- without toolchain: unknown
- with: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/ba417d80b1174d0e289d8fc91c77a8f6a0d592f4/opencode'
- with toolchain: unknown
- cumulative spend (all phases, est.): $432.34
- SDK: without: (no toolchain); with: (no toolchain); sdk_changed=''

## PR 5140 (exit 0, 15:44 ET)
- PR 5140: without: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/3a179fcd34aed5d91b6dd0c522bec419494356db/opencode') | with: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/75a4dcbce833a318b825f2310444337910d0cc3a/opencode'); SDK without[unknown] with[unknown]
- without: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/3a179fcd34aed5d91b6dd0c522bec419494356db/opencode'
- without toolchain: unknown
- with: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/75a4dcbce833a318b825f2310444337910d0cc3a/opencode'
- with toolchain: unknown
- cumulative spend (all phases, est.): $432.34
- SDK: without: (no toolchain); with: (no toolchain); sdk_changed=''

## PR 5527 (exit 0, 15:44 ET)
- PR 5527: without: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/6d412d8872adda1e059f284bc591d3928eebeef5/opencode') | with: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/92948ed8a49a2701ffa353c93a271a66e9637f99/opencode'); SDK without[unknown] with[unknown]
- without: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/6d412d8872adda1e059f284bc591d3928eebeef5/opencode'
- without toolchain: unknown
- with: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/92948ed8a49a2701ffa353c93a271a66e9637f99/opencode'
- with toolchain: unknown
- cumulative spend (all phases, est.): $432.34
- SDK: without: (no toolchain); with: (no toolchain); sdk_changed=''

## PR 6524 (exit 0, 15:45 ET)
- PR 6524: without: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/decc616c800827e1e28c96fe2253ee229095dc23/opencode') | with: infra (exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/f3db96631704f5d7cf2ee6c2a31812d161305356/opencode'); SDK without[unknown] with[unknown]
- without: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/decc616c800827e1e28c96fe2253ee229095dc23/opencode'
- without toolchain: unknown
- with: infra — exec failed: [Errno 2] No such file or directory: '/workspace/openbench-ab/results/opencode-src/bin/f3db96631704f5d7cf2ee6c2a31812d161305356/opencode'
- with toolchain: unknown
- cumulative spend (all phases, est.): $432.34
- SDK: without: (no toolchain); with: (no toolchain); sdk_changed=''
