ENOENT-set PR #4204 done (exit 0, 17:16 ET) @ 019ad6e / PR #8

Researcher scoring lock (report only — do NOT claim clear for mid-era rows):
- Primary: pass 0.000→0.000; wall 5.7→5.0s (-13.4%); out_tok 14.9→14.9; non-cache input 4.0→4.0 (proxy_in 4.0→4.0)
- Tokens total/cell: 15k→15k (-0.0%)
- $ secondary: $/cell 0.040→0.037 (-6.4%); PR$ ~1.84
- FLAG tok vs $ diverge: tok Δ -0.0% vs cost Δ -6.4% (gap 6.4pp)

| side | n | pass | wall_s | out_tok | noncache_in | tok/cell | $/cell |
|---|---|---|---|---|---|---|---|
| without | 24 | 0.000 | 5.7 | 14.9 | 4.0 | 15k | 0.040 |
| with | 24 | 0.000 | 5.0 | 14.9 | 4.0 | 15k | 0.037 |
- Metering: proxy={'proxy_measured': 22, None: 2}/{'proxy_measured': 22, None: 2}; classes={'infra': 22, 'incompatible': 2}/{'infra': 22, 'incompatible': 2}; unmetered=2/2
- CR=0; toolchain without={'ai': '5.0.8', 'anthropic': '2.0.0', 'bun': '1.3.2'} with={'ai': '5.0.8', 'anthropic': '2.0.0', 'bun': '1.3.2'}
- cumulative spend est. $478.31 (soft pause $700)
- paths: results/ab/4204/ ; log results/ab-logs/enont-4204.log
