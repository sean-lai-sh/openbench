# PR #2334 harder 5-trial: token/$ bucket breakout

Rates ($/M): {'tokens_input_uncached': 4.0, 'tokens_output': 20.0, 'tokens_cache_read': 0.2, 'tokens_cache_write': 5.0}
Basis: vendor_split on without n=40 with n=40 (n_split 40/40).
`tokens` field = reported total used in prior summaries (NOT full billable sum).

## Per-cell means
### without (n=40)
- reported `tokens`: 191
- row_cost: $0.0402
- input_uncached: 4 tok → $0.0000
- output: 187 tok → $0.0037
- cache_read: 8648 tok → $0.0017
- cache_write: 6939 tok → $0.0347
- sum bucket $: $0.0402

### with (n=40)
- reported `tokens`: 167
- row_cost: $0.0273
- input_uncached: 4 tok → $0.0000
- output: 163 tok → $0.0033
- cache_read: 11243 tok → $0.0022
- cache_write: 4344 tok → $0.0217
- sum bucket $: $0.0273

## Deltas (with − without)
- reported tokens: 191→167 (-12.2%)
- cost: $0.0402→$0.0273 (-32.2%)

- sum of billable buckets: 15777→15754 (-0.1%)

- input_uncached: 4→4 tok (+0.0%); $0.0000→$0.0000 (+0.0%)
- output: 187→163 tok (-12.4%); $0.0037→$0.0033 (-12.4%)
- cache_read: 8648→11243 tok (+30.0%); $0.0017→$0.0022 (+30.0%)
- cache_write: 6939→4344 tok (-37.4%); $0.0347→$0.0217 (-37.4%)

## $ share of cell cost
- without: input_uncached 0.0%, output 9.3%, cache_read 4.3%, cache_write 86.4%
- with: input_uncached 0.1%, output 12.0%, cache_read 8.3%, cache_write 79.7%

## Per-task (reported tok Δ% | cost Δ% | output Δ% | input_uncached Δ% | cache_read Δ% | cache_write Δ%)
- add-feature: tok +0.4% | cost -54.6% | out +0.4% | in_u +0.0% | cache_r +inf% | cache_w -58.9%
- build-a-cli: tok -30.6% | cost -56.1% | out -30.8% | in_u +0.0% | cache_r +150.0% | cache_w -64.0%
- fix-failing-test: tok +3.2% | cost +0.4% | out +3.3% | in_u +0.0% | cache_r +0.0% | cache_w -0.0%
- make-ci-green: tok -4.8% | cost -32.9% | out -4.9% | in_u +0.0% | cache_r +25.0% | cache_w -39.2%
- make-it-run: tok -9.7% | cost -1.3% | out -9.9% | in_u +0.0% | cache_r +0.0% | cache_w +0.0%
- misleading-error: tok -10.0% | cost -1.6% | out -10.2% | in_u +0.0% | cache_r +0.0% | cache_w -0.0%
- taskflow: tok -1.8% | cost -31.1% | out -1.8% | in_u +0.0% | cache_r +25.0% | cache_w -36.9%
- webcore: tok -1.6% | cost -0.1% | out -1.6% | in_u +0.0% | cache_r +0.0% | cache_w +0.0%

## $ delta attribution
- input_uncached: $+0.0000 (-0% of Δcost)
- output: $-0.0005 (4% of Δcost)
- cache_read: $+0.0005 (-4% of Δcost)
- cache_write: $-0.0130 (100% of Δcost)
- sum contrib $-0.0129 vs Δcost $-0.0129

## Primary metrics (means)
- output tokens: 187→163 (-12.4%)
- input_uncached: 4→4 (+0.0%)
