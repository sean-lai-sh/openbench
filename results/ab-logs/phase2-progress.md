# Phase 2 progress

Cap: cumulative est. spend < $850 (enforced by phase2.sh watchdog; runner --max-cost-usd unusable because 623's unmetered cells block all launches).

## PR 3052 (exit 0, 22:34 ET)
- without: n=24 pass=0.042 wall=5.8s turns=n/a tok/cell=n/a cost/cell=$0.000 classes={'infra': 12, 'wrong_answer': 10, 'rate_limited': 1, 'solved': 1} UNMETERED=24
- with: n=24 pass=0.042 wall=5.1s turns=n/a tok/cell=n/a cost/cell=$0.000 classes={'infra': 12, 'wrong_answer': 11, 'solved': 1} UNMETERED=24
- cumulative spend (all phases, est.): $63.13

## PR 3115 (exit 0, 22:36 ET)
- without: n=24 pass=0.042 wall=5.3s turns=n/a tok/cell=n/a cost/cell=$0.000 classes={'infra': 12, 'wrong_answer': 11, 'solved': 1} UNMETERED=24
- with: n=24 pass=0.042 wall=5.1s turns=n/a tok/cell=n/a cost/cell=$0.000 classes={'infra': 12, 'wrong_answer': 11, 'solved': 1} UNMETERED=24
- cumulative spend (all phases, est.): $63.13

## PR 3369 (exit 0, 22:38 ET)
- without: n=24 pass=0.000 wall=5.3s turns=n/a tok/cell=n/a cost/cell=$0.000 classes={'infra': 24} UNMETERED=24
- with: n=24 pass=0.042 wall=5.5s turns=n/a tok/cell=n/a cost/cell=$0.000 classes={'infra': 23, 'solved': 1} UNMETERED=24
- cumulative spend (all phases, est.): $63.13

## PR 3418 (exit 0, 22:40 ET)
- without: n=24 pass=0.125 wall=6.4s turns=n/a tok/cell=n/a cost/cell=$0.000 classes={'infra': 21, 'solved': 3} UNMETERED=24
- with: n=24 pass=0.042 wall=5.8s turns=n/a tok/cell=n/a cost/cell=$0.000 classes={'infra': 23, 'solved': 1} UNMETERED=24
- cumulative spend (all phases, est.): $63.13

## PR 4204 (exit 0, 22:40 ET)
- without: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- with: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- cumulative spend (all phases, est.): $63.13

## PR 4838 (exit 0, 22:41 ET)
- without: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- with: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- cumulative spend (all phases, est.): $63.13

## PR 5066 (exit 0, 22:41 ET)
- without: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- with: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- cumulative spend (all phases, est.): $63.13

## PR 5131 (exit 0, 22:42 ET)
- without: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- with: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- cumulative spend (all phases, est.): $63.13

## PR 5140 (exit 0, 22:42 ET)
- without: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- with: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- cumulative spend (all phases, est.): $63.13

## PR 5527 (exit 0, 22:43 ET)
- without: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- with: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- cumulative spend (all phases, est.): $63.13

## PR 6524 (exit 0, 22:43 ET)
- without: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- with: INCOMPATIBLE (not listed while loading anthropic/claude-opus-5-5)
- cumulative spend (all phases, est.): $63.13

## PR 11731 (exit 0, 23:00 ET)
- without: n=24 pass=1.000 wall=98.8s turns=8.0 tok/cell=257071.5 cost/cell=$0.517 classes={'solved': 24}
- with: n=24 pass=1.000 wall=112.1s turns=8.0 tok/cell=256548.3 cost/cell=$0.532 classes={'solved': 24}
- cumulative spend (all phases, est.): $88.31

## PR 12214 (exit 0, 23:18 ET)
- without: n=24 pass=1.000 wall=104.1s turns=7.4 tok/cell=234528.2 cost/cell=$0.496 classes={'solved': 24}
- with: n=24 pass=1.000 wall=107.4s turns=7.7 tok/cell=252872.4 cost/cell=$0.526 classes={'solved': 24}
- cumulative spend (all phases, est.): $112.82

> Note (23:3x ET): PRs 3052/3115/3369/3418 cells and 4204/4838/5066/5131/5140/5527/6524 incompatible sidecars were moved to results/ab-quarantine/phase2/ (runner bugs: DecimalError on v0.14-0.15 builds; musl binary picked on v1.0.x builds). See README there.

## PR 13090 (exit 0, 23:36 ET)
- without: n=24 pass=1.000 wall=105.2s turns=7.8 tok/cell=254991.4 cost/cell=$0.533 classes={'solved': 24}
- with: n=24 pass=1.000 wall=111.4s turns=7.8 tok/cell=245412.5 cost/cell=$0.542 classes={'solved': 24}
- cumulative spend (all phases, est.): $138.62

## PR 13198 (exit 0, 23:49 ET)
- without: n=24 pass=1.000 wall=99.2s turns=7.5 tok/cell=240366.9 cost/cell=$0.497 classes={'solved': 24}
- with: n=24 pass=1.000 wall=94.6s turns=7.1 tok/cell=226154.4 cost/cell=$0.470 classes={'solved': 24}
- cumulative spend (all phases, est.): $161.83

## PR 13269 (exit 0, 00:04 ET)
- without: n=24 pass=1.000 wall=106.0s turns=7.5 tok/cell=241276.3 cost/cell=$0.559 classes={'solved': 24}
- with: n=24 pass=1.000 wall=95.9s turns=7.6 tok/cell=246098.7 cost/cell=$0.531 classes={'solved': 24}
- cumulative spend (all phases, est.): $187.99

## PR 13331 (exit 0, 00:23 ET)
- without: n=24 pass=1.000 wall=102.7s turns=7.1 tok/cell=221093.3 cost/cell=$0.529 classes={'solved': 24}
- with: n=24 pass=1.000 wall=117.1s turns=8.2 tok/cell=279911.4 cost/cell=$0.559 classes={'solved': 24}
- cumulative spend (all phases, est.): $214.09

## PR 17053 (exit 0, 00:39 ET)
- without: n=24 pass=1.000 wall=103.8s turns=8.0 tok/cell=259798.5 cost/cell=$0.524 classes={'solved': 24}
- with: n=24 pass=1.000 wall=99.7s turns=7.8 tok/cell=251226.5 cost/cell=$0.518 classes={'solved': 24}
- cumulative spend (all phases, est.): $239.10

## PR 19058 (exit 0, 00:54 ET)
- without: n=24 pass=1.000 wall=89.5s turns=7.4 tok/cell=233610.1 cost/cell=$0.485 classes={'solved': 24}
- with: n=24 pass=1.000 wall=98.9s turns=7.8 tok/cell=239214.5 cost/cell=$0.518 classes={'solved': 24}
- cumulative spend (all phases, est.): $263.19

## PR 21070 (exit 0, 01:12 ET)
- without: n=24 pass=1.000 wall=117.2s turns=7.3 tok/cell=222397.0 cost/cell=$0.448 classes={'solved': 24}
- with: n=24 pass=1.000 wall=113.3s turns=7.1 tok/cell=215337.9 cost/cell=$0.456 classes={'solved': 24}
- cumulative spend (all phases, est.): $284.88

## PR 22390 (exit 0, 01:29 ET)
- without: n=24 pass=1.000 wall=108.9s turns=6.9 tok/cell=204161.3 cost/cell=$0.439 classes={'solved': 24}
- with: n=24 pass=1.000 wall=120.9s turns=7.1 tok/cell=212427.2 cost/cell=$0.487 classes={'solved': 24}
- cumulative spend (all phases, est.): $307.12

## PR 23771 (exit 0, 01:40 ET)
- without: n=24 pass=1.000 wall=87.1s turns=6.6 tok/cell=193178.1 cost/cell=$0.460 classes={'solved': 24}
- with: n=24 pass=1.000 wall=69.7s turns=6.1 tok/cell=173721.4 cost/cell=$0.412 classes={'solved': 24}
- cumulative spend (all phases, est.): $328.06

## PR 24974 (exit 0, 01:53 ET)
- without: n=24 pass=1.000 wall=71.0s turns=5.9 tok/cell=166037.7 cost/cell=$0.405 classes={'solved': 24}
- with: n=24 pass=1.000 wall=78.4s turns=6.1 tok/cell=178101.9 cost/cell=$0.420 classes={'solved': 24}
- cumulative spend (all phases, est.): $347.85

## PR 25226 (exit 0, 02:05 ET)
- without: n=24 pass=1.000 wall=86.7s turns=6.3 tok/cell=197030.9 cost/cell=$0.438 classes={'solved': 24}
- with: n=24 pass=1.000 wall=77.3s turns=6.7 tok/cell=208985.0 cost/cell=$0.421 classes={'solved': 24}
- cumulative spend (all phases, est.): $368.45

## PR 25431 (exit 0, 02:17 ET)
- without: n=24 pass=1.000 wall=86.2s turns=6.5 tok/cell=202482.8 cost/cell=$0.435 classes={'solved': 24}
- with: n=24 pass=1.000 wall=75.6s turns=6.0 tok/cell=177656.5 cost/cell=$0.422 classes={'solved': 24}
- cumulative spend (all phases, est.): $389.02

## PR 17098-aa (A/A noise check)
- without: n=24 pass=1.000 wall=94.2s turns=7.0 tok/cell=215241.7 cost/cell=$0.495 classes={'solved': 24}
- with: n=24 pass=1.000 wall=104.4s turns=8.2 tok/cell=256165.5 cost/cell=$0.532 classes={'solved': 24}
- cumulative spend (all phases, est.): $413.67
