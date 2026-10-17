# Harder-task 5-trial progress (@ e04d456 / PR #6)

PRs (order): 26821, 13331, 23771, 2334, 3115.
Command: `python3 -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr <PR> --trials 5 --jobs 8 --out results/ab --cache /workspace/openbench-ab/results/opencode-src` (all 8 core tasks).
Soft cap CAP=$700 HEADROOM=$40. Prior cumulative ~$432.34; phase est ~$200–250; pause past ~$700.
3-trial cells quarantined under `results/ab-quarantine/pre-hard5-<pr>/` then wiped so run_ab does not skip trials 1–3.
Noise floor (first-pass A/A): ±12% wall, ±19% tokens, ±11% cost — applies to 26821/13331/23771.
2334/3115: set-aside 3-trial was tiny (~5s/16k, pass 0→0); prior CLEAR not confirmed under that floor.
Report tok and cost Δ% side by side; FLAG if |tok Δ% − cost Δ%| > 5pp.

Prior=$432.34 live0_after_wipe=$367.04 HEAD=e04d456 started 2026-10-05T15:49:09-04:00.


## PR 26821 (exit 0, 15:59 ET)
- PR 26821: pass 1.000→1.000; wall 42.4→46.4s (+9.5%); turns 5.2→6.0; tok 146k→157k (+7.8%); cost $0.347→$0.295 (-15.1%); PR $25.70; noise_floor=CLEAR; SDK without[bun=1.3.13,ai=6.0.168,anthropic=3.0.64] with[bun=1.3.13,ai=6.0.168,anthropic=3.0.64] | FLAG: PR-aggregate token Δ% (+7.8%) vs cost Δ% (-15.1%) disagree by 22.9pp (>5pp) — likely metering/counting, not harness | FLAG: task add-feature: tok Δ%=-4.7% cost Δ%=-23.8% (disagree 19.1pp); fail n 0→0 | FLAG: task fix-failing-test: tok Δ%=-36.5% cost Δ%=-41.6% (disagree 5.1pp); fail n 0→0 | FLAG: task make-ci-green: tok Δ%=-38.6% cost Δ%=-44.8% (disagree 6.1pp); fail n 0→0 | FLAG: task make-it-run: tok Δ%=-27.6% cost Δ%=-20.9% (disagree 6.7pp); fail n 0→0 | FLAG: task taskflow: tok Δ%=+25.1% cost Δ%=-8.2% (disagree 33.3pp); fail n 0→0 | FLAG: task webcore: tok Δ%=+24.6% cost Δ%=+9.3% (disagree 15.3pp); fail n 0→0
- without: n=40 pass=1.000 wall=42.4s turns=5.2 tok/cell=145683 cost/cell=$0.347 (n_ok=40 n_fail=0)
- without toolchain: bun=1.3.13,ai=6.0.168,anthropic=3.0.64
- with: n=40 pass=1.000 wall=46.4s turns=6.0 tok/cell=157112 cost/cell=$0.295 (n_ok=40 n_fail=0)
- with toolchain: bun=1.3.13,ai=6.0.168,anthropic=3.0.64
- tok vs cost: tok 145683→157112 (Δ +7.8%); cost $0.347→$0.295 (Δ -15.1%)
- **FLAG:** PR-aggregate token Δ% (+7.8%) vs cost Δ% (-15.1%) disagree by 22.9pp (>5pp) — likely metering/counting, not harness
- **FLAG:** task add-feature: tok Δ%=-4.7% cost Δ%=-23.8% (disagree 19.1pp); fail n 0→0
- **FLAG:** task fix-failing-test: tok Δ%=-36.5% cost Δ%=-41.6% (disagree 5.1pp); fail n 0→0
- **FLAG:** task make-ci-green: tok Δ%=-38.6% cost Δ%=-44.8% (disagree 6.1pp); fail n 0→0
- **FLAG:** task make-it-run: tok Δ%=-27.6% cost Δ%=-20.9% (disagree 6.7pp); fail n 0→0
- **FLAG:** task taskflow: tok Δ%=+25.1% cost Δ%=-8.2% (disagree 33.3pp); fail n 0→0
- **FLAG:** task webcore: tok Δ%=+24.6% cost Δ%=+9.3% (disagree 15.3pp); fail n 0→0
- cumulative spend (all phases, est.): $458.03 (prior=$432.34 hard5_new=$25.69)
- SDK: without: bun=1.3.13, ai=6.0.168, anthropic=3.0.64; with: bun=1.3.13, ai=6.0.168, anthropic=3.0.64; sdk_changed=''

## PR 13331 (exit 0, 16:39 ET)
- PR 13331: pass 0.900→0.900; wall 118.0→124.5s (+5.5%); turns 5.9→5.8; tok 166k→137k (-17.4%); cost $0.430→$0.369 (-14.2%); PR $31.96; noise_floor=CLEAR; SDK without[bun=1.3.5,ai=5.0.124,anthropic=2.0.77] with[bun=1.3.5,ai=5.0.124,anthropic=2.0.77] | FLAG: task build-a-cli: tok Δ%=-9.2% cost Δ%=+14.0% (disagree 23.2pp); fail n 0→0 | FLAG: task fix-failing-test: tok Δ%=+4.5% cost Δ%=+10.4% (disagree 5.9pp); fail n 0→0 | FLAG: task make-it-run: tok Δ%=-0.2% cost Δ%=+14.9% (disagree 15.1pp); fail n 0→0 | FLAG: task taskflow: tok Δ%=+7.0% cost Δ%=+0.4% (disagree 6.6pp); fail n 0→0 | FLAG: task webcore: tok Δ%=-45.0% cost Δ%=-50.5% (disagree 5.5pp); fail n 4→4
- without: n=40 pass=0.900 wall=118.0s turns=5.9 tok/cell=165703 cost/cell=$0.430 (n_ok=36 n_fail=4)
- without toolchain: bun=1.3.5,ai=5.0.124,anthropic=2.0.77
- with: n=40 pass=0.900 wall=124.5s turns=5.8 tok/cell=136793 cost/cell=$0.369 (n_ok=36 n_fail=4)
- with toolchain: bun=1.3.5,ai=5.0.124,anthropic=2.0.77
- tok vs cost: tok 165703→136793 (Δ -17.4%); cost $0.430→$0.369 (Δ -14.2%)
- **FLAG:** task build-a-cli: tok Δ%=-9.2% cost Δ%=+14.0% (disagree 23.2pp); fail n 0→0
- **FLAG:** task fix-failing-test: tok Δ%=+4.5% cost Δ%=+10.4% (disagree 5.9pp); fail n 0→0
- **FLAG:** task make-it-run: tok Δ%=-0.2% cost Δ%=+14.9% (disagree 15.1pp); fail n 0→0
- **FLAG:** task taskflow: tok Δ%=+7.0% cost Δ%=+0.4% (disagree 6.6pp); fail n 0→0
- **FLAG:** task webcore: tok Δ%=-45.0% cost Δ%=-50.5% (disagree 5.5pp); fail n 4→4
- cumulative spend (all phases, est.): $490.00 (prior=$432.34 hard5_new=$57.66)
- SDK: without: bun=1.3.5, ai=5.0.124, anthropic=2.0.77; with: bun=1.3.5, ai=5.0.124, anthropic=2.0.77; sdk_changed=''

## PR 23771 (exit 0, 16:57 ET)
- PR 23771: pass 1.000→1.000; wall 70.9→83.6s (+17.9%); turns 6.0→6.3; tok 180k→193k (+7.3%); cost $0.403→$0.434 (+7.5%); PR $33.48; noise_floor=CLEAR; SDK without[bun=1.3.13,ai=6.0.168,anthropic=3.0.64] with[bun=1.3.13,ai=6.0.168,anthropic=3.0.64] | FLAG: task add-feature: tok Δ%=+9.0% cost Δ%=-10.0% (disagree 19.1pp); fail n 0→0 | FLAG: task build-a-cli: tok Δ%=+0.2% cost Δ%=+31.4% (disagree 31.3pp); fail n 0→0 | FLAG: task make-it-run: tok Δ%=-4.6% cost Δ%=+4.7% (disagree 9.3pp); fail n 0→0 | FLAG: task misleading-error: tok Δ%=-5.8% cost Δ%=-18.3% (disagree 12.5pp); fail n 0→0 | FLAG: task taskflow: tok Δ%=-7.8% cost Δ%=+5.8% (disagree 13.6pp); fail n 0→0
- without: n=40 pass=1.000 wall=70.9s turns=6.0 tok/cell=179659 cost/cell=$0.403 (n_ok=40 n_fail=0)
- without toolchain: bun=1.3.13,ai=6.0.168,anthropic=3.0.64
- with: n=40 pass=1.000 wall=83.6s turns=6.3 tok/cell=192849 cost/cell=$0.434 (n_ok=40 n_fail=0)
- with toolchain: bun=1.3.13,ai=6.0.168,anthropic=3.0.64
- tok vs cost: tok 179659→192849 (Δ +7.3%); cost $0.403→$0.434 (Δ +7.5%)
- **FLAG:** task add-feature: tok Δ%=+9.0% cost Δ%=-10.0% (disagree 19.1pp); fail n 0→0
- **FLAG:** task build-a-cli: tok Δ%=+0.2% cost Δ%=+31.4% (disagree 31.3pp); fail n 0→0
- **FLAG:** task make-it-run: tok Δ%=-4.6% cost Δ%=+4.7% (disagree 9.3pp); fail n 0→0
- **FLAG:** task misleading-error: tok Δ%=-5.8% cost Δ%=-18.3% (disagree 12.5pp); fail n 0→0
- **FLAG:** task taskflow: tok Δ%=-7.8% cost Δ%=+5.8% (disagree 13.6pp); fail n 0→0
- cumulative spend (all phases, est.): $523.48 (prior=$432.34 hard5_new=$91.14)
- SDK: without: bun=1.3.13, ai=6.0.168, anthropic=3.0.64; with: bun=1.3.13, ai=6.0.168, anthropic=3.0.64; sdk_changed=''

## PR 2334 (exit 0, 16:58 ET)
- PR 2334: pass 0.000→0.000; wall 5.0→4.5s (-9.5%); turns n/a→n/a; tok 16k→16k (-0.1%); cost $0.040→$0.027 (-32.2%); PR $2.70; noise_floor=CLEAR* (tiny-cell cohort; first-pass A/A ±12/±19/±11 not applied as confirmed floor); SDK without[bun=1.2.19,ai=5.0.8,anthropic=2.0.0] with[bun=1.2.19,ai=5.0.8,anthropic=2.0.0] | FLAG: PR-aggregate token Δ% (-0.1%) vs cost Δ% (-32.2%) disagree by 32.0pp (>5pp) — likely metering/counting, not harness | FLAG: task add-feature: tok Δ%=+0.0% cost Δ%=-54.6% (disagree 54.6pp); fail n 5→5 | FLAG: task build-a-cli: tok Δ%=-0.9% cost Δ%=-56.1% (disagree 55.2pp); fail n 5→5 | FLAG: task make-ci-green: tok Δ%=-0.0% cost Δ%=-32.9% (disagree 32.9pp); fail n 5→5 | FLAG: task taskflow: tok Δ%=-0.0% cost Δ%=-31.1% (disagree 31.1pp); fail n 5→5 | FLAG: $/cell fail mix: without n_fail=40 fail_cost_mean=$0.0402 (40 costed); with n_fail=40 fail_cost_mean=$0.0273 (40 costed). Check whether $/cell includes failed/retry cells differently after vs before.
- without: n=40 pass=0.000 wall=5.0s turns=n/a tok/cell=15777 cost/cell=$0.040 (n_ok=0 n_fail=40)
- without toolchain: bun=1.2.19,ai=5.0.8,anthropic=2.0.0
- with: n=40 pass=0.000 wall=4.5s turns=n/a tok/cell=15754 cost/cell=$0.027 (n_ok=0 n_fail=40)
- with toolchain: bun=1.2.19,ai=5.0.8,anthropic=2.0.0
- tok vs cost: tok 15777→15754 (Δ -0.1%); cost $0.040→$0.027 (Δ -32.2%)
- **FLAG:** PR-aggregate token Δ% (-0.1%) vs cost Δ% (-32.2%) disagree by 32.0pp (>5pp) — likely metering/counting, not harness
- **FLAG:** task add-feature: tok Δ%=+0.0% cost Δ%=-54.6% (disagree 54.6pp); fail n 5→5
- **FLAG:** task build-a-cli: tok Δ%=-0.9% cost Δ%=-56.1% (disagree 55.2pp); fail n 5→5
- **FLAG:** task make-ci-green: tok Δ%=-0.0% cost Δ%=-32.9% (disagree 32.9pp); fail n 5→5
- **FLAG:** task taskflow: tok Δ%=-0.0% cost Δ%=-31.1% (disagree 31.1pp); fail n 5→5
- **FLAG:** $/cell fail mix: without n_fail=40 fail_cost_mean=$0.0402 (40 costed); with n_fail=40 fail_cost_mean=$0.0273 (40 costed). Check whether $/cell includes failed/retry cells differently after vs before.
- note: set-aside 3-trial was tiny (~5s/16k, pass 0→0); do not treat prior CLEAR as confirmed under first-pass A/A noise floor.
- cumulative spend (all phases, est.): $526.18 (prior=$432.34 hard5_new=$93.84)
- SDK: without: bun=1.2.19, ai=5.0.8, anthropic=2.0.0; with: bun=1.2.19, ai=5.0.8, anthropic=2.0.0; sdk_changed=''

## PR 3115 (exit 0, 16:59 ET)
- PR 3115: pass 0.000→0.000; wall 5.1→4.8s (-4.2%); turns n/a→n/a; tok 16k→16k (+0.1%); cost $0.046→$0.042 (-8.9%); PR $3.48; noise_floor=within* (tiny-cell cohort; first-pass A/A ±12/±19/±11 not applied as confirmed floor); SDK without[bun=1.3.0,ai=5.0.8,anthropic=2.0.0] with[bun=1.3.0,ai=5.0.8,anthropic=2.0.0] | FLAG: PR-aggregate token Δ% (+0.1%) vs cost Δ% (-8.9%) disagree by 8.9pp (>5pp) — likely metering/counting, not harness | FLAG: task build-a-cli: tok Δ%=+0.3% cost Δ%=-27.9% (disagree 28.2pp); fail n 5→5 | FLAG: task misleading-error: tok Δ%=+0.1% cost Δ%=-29.8% (disagree 29.9pp); fail n 5→5 | FLAG: $/cell fail mix: without n_fail=40 fail_cost_mean=$0.0456 (40 costed); with n_fail=40 fail_cost_mean=$0.0415 (40 costed). Check whether $/cell includes failed/retry cells differently after vs before.
- without: n=40 pass=0.000 wall=5.1s turns=n/a tok/cell=16073 cost/cell=$0.046 (n_ok=0 n_fail=40)
- without toolchain: bun=1.3.0,ai=5.0.8,anthropic=2.0.0
- with: n=40 pass=0.000 wall=4.8s turns=n/a tok/cell=16085 cost/cell=$0.042 (n_ok=0 n_fail=40)
- with toolchain: bun=1.3.0,ai=5.0.8,anthropic=2.0.0
- tok vs cost: tok 16073→16085 (Δ +0.1%); cost $0.046→$0.042 (Δ -8.9%)
- **FLAG:** PR-aggregate token Δ% (+0.1%) vs cost Δ% (-8.9%) disagree by 8.9pp (>5pp) — likely metering/counting, not harness
- **FLAG:** task build-a-cli: tok Δ%=+0.3% cost Δ%=-27.9% (disagree 28.2pp); fail n 5→5
- **FLAG:** task misleading-error: tok Δ%=+0.1% cost Δ%=-29.8% (disagree 29.9pp); fail n 5→5
- **FLAG:** $/cell fail mix: without n_fail=40 fail_cost_mean=$0.0456 (40 costed); with n_fail=40 fail_cost_mean=$0.0415 (40 costed). Check whether $/cell includes failed/retry cells differently after vs before.
- note: set-aside 3-trial was tiny (~5s/16k, pass 0→0); do not treat prior CLEAR as confirmed under first-pass A/A noise floor.
- cumulative spend (all phases, est.): $529.66 (prior=$432.34 hard5_new=$97.32)
- SDK: without: bun=1.3.0, ai=5.0.8, anthropic=2.0.0; with: bun=1.3.0, ai=5.0.8, anthropic=2.0.0; sdk_changed=''
