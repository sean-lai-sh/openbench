# PR #26821 harder 5-trial: token/$ bucket breakout

Rates ($/M): {'tokens_input_uncached': 4.0, 'tokens_output': 20.0, 'tokens_cache_read': 0.2, 'tokens_cache_write': 5.0}
Basis: vendor_split on all 80 cells (proxy_measured also present).
`tokens` field = fresh/output-ish reported total used in prior summaries (NOT full billable sum).

## Per-cell means
### without (n=40)
- reported `tokens`: 3530
- row_cost: $0.3474
- input_uncached: 12 tok → $0.0000
- output: 3517 tok → $0.0703
- cache_read: 90367 tok → $0.0181
- cache_write: 51786 tok → $0.2589
- sum bucket $: $0.3474

### with (n=40)
- reported `tokens`: 4048
- row_cost: $0.2950
- input_uncached: 14 tok → $0.0001
- output: 4034 tok → $0.0807
- cache_read: 114796 tok → $0.0230
- cache_write: 38268 tok → $0.1913
- sum bucket $: $0.2950

## Deltas (with − without)
- reported tokens: 3530→4048 (+14.7%)
- cost: $0.3474→$0.2950 (-15.1%)

- sum of billable buckets: 145683→157112 (+7.8%)

- input_uncached: 12→14 tok (+13.0%); $0.0000→$0.0001 (+13.0%)
- output: 3517→4034 tok (+14.7%); $0.0703→$0.0807 (+14.7%)
- cache_read: 90367→114796 tok (+27.0%); $0.0181→$0.0230 (+27.0%)
- cache_write: 51786→38268 tok (-26.1%); $0.2589→$0.1913 (-26.1%)

## $ share of cell cost
- without: input_uncached 0.0%, output 20.3%, cache_read 5.2%, cache_write 74.5%
- with: input_uncached 0.0%, output 27.3%, cache_read 7.8%, cache_write 64.9%

## Per-task (reported tok Δ% | cost Δ% | output Δ% | cache_read Δ%)
- add-feature: tok +35.4% | cost -23.8% | out +35.5% | cache_r +24.6%
- build-a-cli: tok +0.4% | cost -19.7% | out +0.3% | cache_r -27.6%
- fix-failing-test: tok -5.7% | cost -41.6% | out -5.7% | cache_r -5.2%
- make-ci-green: tok -24.7% | cost -44.8% | out -24.8% | cache_r -4.6%
- make-it-run: tok +8.7% | cost -20.9% | out +8.8% | cache_r -40.6%
- misleading-error: tok +27.2% | cost -20.2% | out +27.6% | cache_r -26.7%
- taskflow: tok +46.5% | cost -8.2% | out +46.6% | cache_r +50.3%
- webcore: tok +12.8% | cost +9.3% | out +12.8% | cache_r +28.3%

## $ delta attribution
- input_uncached: $+0.0000 (-0% of Δcost)
- output: $+0.0103 (-20% of Δcost)
- cache_read: $+0.0049 (-9% of Δcost)
- cache_write: $-0.0676 (129% of Δcost)
- sum contrib $-0.0524 vs Δcost $-0.0524