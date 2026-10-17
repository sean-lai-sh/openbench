ENOENT-set PR #5131 done (exit 0, 17:32 ET) @ 019ad6e / PR #8

Researcher scoring lock (report only — do NOT claim clear for mid-era rows):
- Primary: pass 1.000→1.000; wall 50.4→52.5s (+4.3%); out_tok 4645.5→4874.5; non-cache input 15.7→16.8 (proxy_in 1269.9→1271.0)
- Tokens total/cell: 190k→221k (+16.4%)
- $ secondary: $/cell 0.268→0.256 (-4.4%); PR$ ~12.57
- FLAG tok vs $ diverge: tok Δ +16.4% vs cost Δ -4.4% (gap 20.7pp)

| side | n | pass | wall_s | out_tok | noncache_in | tok/cell | $/cell |
|---|---|---|---|---|---|---|---|
| without | 24 | 1.000 | 50.4 | 4645.5 | 15.7 | 190k | 0.268 |
| with | 24 | 1.000 | 52.5 | 4874.5 | 16.8 | 221k | 0.256 |
- Metering: proxy={'proxy_measured': 24}/{'proxy_measured': 24}; classes={'solved': 24}/{'solved': 24}; unmetered=0/0
- CR=0; toolchain without={'ai': '5.0.97', 'anthropic': '2.0.0', 'bun': '1.3.3'} with={'ai': '5.0.97', 'anthropic': '2.0.0', 'bun': '1.3.3'}
- cumulative spend est. $502.70 (soft pause $700)
- paths: results/ab/5131/ ; log results/ab-logs/enont-5131.log
