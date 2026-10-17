# PR #23771 harder 5-trial: token/$ bucket breakout

Rates ($/M): {'tokens_input_uncached': 4.0, 'tokens_output': 20.0, 'tokens_cache_read': 0.2, 'tokens_cache_write': 5.0}
Basis: vendor_split on without n=40 with n=40 (n_split 40/40).
`tokens` field = reported total used in prior summaries (NOT full billable sum).

## Per-cell means
### without (n=40)
- reported `tokens`: 6438
- row_cost: $0.4035
- input_uncached: 14 tok → $0.0001
- output: 6424 tok → $0.1285
- cache_read: 123161 tok → $0.0246
- cache_write: 50060 tok → $0.2503
- sum bucket $: $0.4035

### with (n=40)
- reported `tokens`: 7789
- row_cost: $0.4336
- input_uncached: 15 tok → $0.0001
- output: 7775 tok → $0.1555
- cache_read: 134837 tok → $0.0270
- cache_write: 50222 tok → $0.2511
- sum bucket $: $0.4336

## Deltas (with − without)
- reported tokens: 6438→7789 (+21.0%)
- cost: $0.4035→$0.4336 (+7.5%)

- sum of billable buckets: 179659→192849 (+7.3%)

- input_uncached: 14→15 tok (+3.2%); $0.0001→$0.0001 (+3.2%)
- output: 6424→7775 tok (+21.0%); $0.1285→$0.1555 (+21.0%)
- cache_read: 123161→134837 tok (+9.5%); $0.0246→$0.0270 (+9.5%)
- cache_write: 50060→50222 tok (+0.3%); $0.2503→$0.2511 (+0.3%)

## $ share of cell cost
- without: input_uncached 0.0%, output 31.8%, cache_read 6.1%, cache_write 62.0%
- with: input_uncached 0.0%, output 35.9%, cache_read 6.2%, cache_write 57.9%

## Per-task (reported tok Δ% | cost Δ% | output Δ% | input_uncached Δ% | cache_read Δ% | cache_write Δ%)
- add-feature: tok +26.3% | cost -10.0% | out +26.4% | in_u +6.1% | cache_r +33.4% | cache_w -21.1%
- build-a-cli: tok +2.8% | cost +31.4% | out +2.9% | in_u +0.0% | cache_r -66.7% | cache_w +38.7%
- fix-failing-test: tok -10.4% | cost -7.0% | out -10.5% | in_u -4.5% | cache_r -0.0% | cache_w -6.8%
- make-ci-green: tok +1.4% | cost +2.2% | out +1.4% | in_u +0.0% | cache_r -11.4% | cache_w +2.5%
- make-it-run: tok -4.2% | cost +4.7% | out -4.2% | in_u -3.6% | cache_r -28.7% | cache_w +5.8%
- misleading-error: tok +6.1% | cost -18.3% | out +6.2% | in_u -4.5% | cache_r +62.3% | cache_w -20.5%
- taskflow: tok -0.9% | cost +5.8% | out -0.8% | in_u -9.1% | cache_r -13.0% | cache_w +9.2%
- webcore: tok +24.1% | cost +18.5% | out +24.1% | in_u +16.1% | cache_r +17.9% | cache_w +1.8%

## $ delta attribution
- input_uncached: $+0.0000 (0% of Δcost)
- output: $+0.0270 (90% of Δcost)
- cache_read: $+0.0023 (8% of Δcost)
- cache_write: $+0.0008 (3% of Δcost)
- sum contrib $+0.0302 vs Δcost $+0.0302

## Primary metrics (means)
- output tokens: 6424→7775 (+21.0%)
- input_uncached: 14→15 (+3.2%)
