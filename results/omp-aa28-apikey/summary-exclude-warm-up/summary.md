# Harness A/B

## Ranked by mean per-task score delta

| PR | Category | Delta score | 95% CI | Paired tasks |
| --- | --- | --- | --- | --- |
| omp-928 | control | 0.000 | 0.000 to 0.000 | 1 |

Pass rate drops rows whose failure class is infra, rate_limited, or stalled.
Watchdog kills are infra cells with infra_reason no_progress, counted per side.
The score delta is the unweighted mean of per-task (with minus without) score means.
The interval resamples those tasks 1000 times with seed 0.
Per-task time, turns, tokens, and cost deltas are with-side means minus without-side means.
Each of those intervals resamples that task's trials 1000 times with seed 0.
Headroom tasks have a mean score below 1.0 on either side. The pass-rate delta there uses only those tasks and the same task bootstrap.

## PR omp-928

Repo: can1357/oh-my-pi
Title: A/A noise floor: row 28 parent vs itself (auth apiKey default)
Category: control
Harness change: None.

| Side | Pass rate | Mean score | Median seconds | Mean tokens |
| --- | --- | --- | --- | --- |
| without | 1.000 | 1.000 | 29.234 | 336640.8 |
| with | 1.000 | 1.000 | 32.058 | 326919.0 |

| Metric | % delta | Raw mean diff |
| --- | --- | --- |
| Output tokens | -4.2% | -84.0 |
| Uncached input | -2.3% | -0.5 |
| Total tokens | -2.9% | -9721.8 |
| Requests | -2.8% | -0.2 |
| Wall s | 8.1% | 2.441 |
| Cost USD | 15.6% | 0.129 |
Watchdog kills (no_progress): without 0, with 0.
Subagent write calls (bash+edit+write+patch): without 0, with 0. Child edit/write/patch (not bash): without 0, with 0. Child plan-mode reminder: without 0, with 0. Workspace changed: without 4, with 4. List output contains generated/: without 0, with 0. dotnet build calls: without 0, with 0. Edit calls: without 0, with 0. Permission rejections: without 0, with 0. Ended on rejection: without 0, with 0. Final answer present: without 4, with 4. Final answer complete (true/false/unknown): without 4/0/0, with 4/0/0. Rule order (global_first/project_first/one/none): without 0/0/0/4, with 0/0/0/4. members.py reads: without 0, with 0. First read window is lines 3-7: without 0, with 0. Exact line-3 quote: without 0, with 0. Leaked temp dirs: without 0, with 0. Scratch dirs left: without 0, with 0. Rule prefix (global/project/both/neither): without 0/0/0/4, with 0/0/0/4. GLOBAL-RULE share (global+both): without 0, with 0. Task calls: without 0, with 0. Subagent resumed: without 0, with 0. Fresh subagents: without 0, with 0. Main agent searched: without 0, with 0. Turn mode (two-turn/single/turn-failure): without 0/0/0, with 0/0/0.

Score delta (with minus without): 0.000 on 1 paired tasks. 95% bootstrap interval: 0.000 to 0.000.

### Per-task deltas

| Task | Time s | 95% CI | Turns | 95% CI | Tokens | 95% CI | Cost USD | 95% CI | Output tokens % | Output tokens diff | Uncached input % | Uncached input diff | Total tokens % | Total tokens diff | Requests % | Requests diff | Wall s % | Wall s diff | Cost USD % | Cost USD diff |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trig-omp-fanout | 2.441 | -2.300 to 6.901 | -0.250 | -1.000 to 0.500 | -9721.8 | -39987.2 to 20126.0 | 0.129 | 0.044 to 0.184 | -4.2% | -84.0 | -2.3% | -0.5 | -2.9% | -9721.8 | -2.8% | -0.2 | 8.1% | 2.441 | 15.6% | 0.129 |

### Headroom

No paired task has a mean score below 1.0 on either side.
