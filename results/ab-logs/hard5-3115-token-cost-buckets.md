# PR #3115 harder 5-trial: token/$ bucket breakout

Rates ($/M): {'tokens_input_uncached': 4.0, 'tokens_output': 20.0, 'tokens_cache_read': 0.2, 'tokens_cache_write': 5.0}
Basis: vendor_split on without n=40 with n=40 (n_split 40/40).
`tokens` field = reported total used in prior summaries (NOT full billable sum).

## Per-cell means
### without (n=40)
- reported `tokens`: 191
- row_cost: $0.0456
- input_uncached: 4 tok → $0.0000
- output: 187 tok → $0.0037
- cache_read: 7836 tok → $0.0016
- cache_write: 8046 tok → $0.0402
- sum bucket $: $0.0456

### with (n=40)
- reported `tokens`: 198
- row_cost: $0.0415
- input_uncached: 4 tok → $0.0000
- output: 194 tok → $0.0039
- cache_read: 8710 tok → $0.0017
- cache_write: 7177 tok → $0.0359
- sum bucket $: $0.0415

## Deltas (with − without)
- reported tokens: 191→198 (+3.4%)
- cost: $0.0456→$0.0415 (-8.9%)

- sum of billable buckets: 16073→16085 (+0.1%)

- input_uncached: 4→4 tok (+0.0%); $0.0000→$0.0000 (+0.0%)
- output: 187→194 tok (+3.5%); $0.0037→$0.0039 (+3.5%)
- cache_read: 7836→8710 tok (+11.2%); $0.0016→$0.0017 (+11.2%)
- cache_write: 8046→7177 tok (-10.8%); $0.0402→$0.0359 (-10.8%)

## $ share of cell cost
- without: input_uncached 0.0%, output 8.2%, cache_read 3.4%, cache_write 88.3%
- with: input_uncached 0.0%, output 9.3%, cache_read 4.2%, cache_write 86.4%

## Per-task (reported tok Δ% | cost Δ% | output Δ% | input_uncached Δ% | cache_read Δ% | cache_write Δ%)
- add-feature: tok +0.7% | cost +0.1% | out +0.7% | in_u +0.0% | cache_r +0.0% | cache_w +0.0%
- build-a-cli: tok +9.3% | cost -27.9% | out +9.3% | in_u +0.0% | cache_r +200.1% | cache_w -34.6%
- fix-failing-test: tok -0.3% | cost +0.0% | out -0.3% | in_u +0.0% | cache_r +0.0% | cache_w +0.0%
- make-ci-green: tok +2.2% | cost +0.3% | out +2.3% | in_u +0.0% | cache_r +0.0% | cache_w -0.0%
- make-it-run: tok -5.1% | cost -0.6% | out -5.3% | in_u +0.0% | cache_r +0.0% | cache_w -0.0%
- misleading-error: tok +5.1% | cost -29.8% | out +5.2% | in_u +0.0% | cache_r +25.1% | cache_w -37.5%
- taskflow: tok +1.0% | cost +0.1% | out +1.0% | in_u +0.0% | cache_r +0.0% | cache_w +0.0%
- webcore: tok +0.9% | cost +0.1% | out +0.9% | in_u +0.0% | cache_r +0.0% | cache_w -0.0%

## $ delta attribution
- input_uncached: $+0.0000 (-0% of Δcost)
- output: $+0.0001 (-3% of Δcost)
- cache_read: $+0.0002 (-4% of Δcost)
- cache_write: $-0.0043 (108% of Δcost)
- sum contrib $-0.0040 vs Δcost $-0.0040

## Primary metrics (means)
- output tokens: 187→194 (+3.5%)
- input_uncached: 4→4 (+0.0%)
