ENOENT-set PR #6524 done (exit 0, 17:56 ET) @ 019ad6e / PR #8

Researcher scoring lock (report only — do NOT claim clear for mid-era rows):
- Primary: pass 1.000→1.000; wall 57.8→51.0s (-11.8%); out_tok 4953.5→4543.1; non-cache input 16.9→15.8 (proxy_in 21.1→19.9)
- Tokens total/cell: 239k→198k (-17.0%)
- $ secondary: $/cell 0.425→0.411 (-3.3%); PR$ ~20.06
- FLAG tok vs $ diverge: tok Δ -17.0% vs cost Δ -3.3% (gap 13.7pp)

| side | n | pass | wall_s | out_tok | noncache_in | tok/cell | $/cell |
|---|---|---|---|---|---|---|---|
| without | 24 | 1.000 | 57.8 | 4953.5 | 16.9 | 239k | 0.425 |
| with | 24 | 1.000 | 51.0 | 4543.1 | 15.8 | 198k | 0.411 |
- Metering: proxy={'proxy_measured': 24}/{'proxy_measured': 24}; classes={'solved': 24}/{'solved': 24}; unmetered=0/0
- CR=0; toolchain without={'ai': '5.0.97', 'anthropic': '2.0.0', 'bun': '1.3.5'} with={'ai': '5.0.97', 'anthropic': '2.0.0', 'bun': '1.3.5'}
- cumulative spend est. $558.80 (soft pause $700)
- paths: results/ab/6524/ ; log results/ab-logs/enont-6524.log
