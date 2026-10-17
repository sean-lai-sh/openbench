ENOENT-set PR #5527 done (exit 0, 17:49 ET) @ 019ad6e / PR #8

Researcher scoring lock (report only — do NOT claim clear for mid-era rows):
- Primary: pass 1.000→1.000; wall 53.2→53.8s (+1.1%); out_tok 4778.2→4602.5; non-cache input 16.5→15.8 (proxy_in 1270.8→1302.0)
- Tokens total/cell: 224k→202k (-9.6%)
- $ secondary: $/cell 0.430→0.424 (-1.3%); PR$ ~20.49
- FLAG tok vs $ diverge: tok Δ -9.6% vs cost Δ -1.3% (gap 8.4pp)

| side | n | pass | wall_s | out_tok | noncache_in | tok/cell | $/cell |
|---|---|---|---|---|---|---|---|
| without | 24 | 1.000 | 53.2 | 4778.2 | 16.5 | 224k | 0.430 |
| with | 24 | 1.000 | 53.8 | 4602.5 | 15.8 | 202k | 0.424 |
- Metering: proxy={'proxy_measured': 24}/{'proxy_measured': 24}; classes={'solved': 24}/{'solved': 24}; unmetered=0/0
- CR=0; toolchain without={'ai': '5.0.97', 'anthropic': '2.0.0', 'bun': '1.3.4'} with={'ai': '5.0.97', 'anthropic': '2.0.0', 'bun': '1.3.4'}
- cumulative spend est. $538.74 (soft pause $700)
- paths: results/ab/5527/ ; log results/ab-logs/enont-5527.log
