# Opus 26821 rerun (H2 deferred), 2026-10-24

- Launch: `h2-deferred-26821.sh`, image h2-env:1022, runner e2ac6b750a3d, jobs=4, seed=1022, $150 hard stop (watcher stops at $148).
- Ran 15:46:03 to 18:45:18 EDT on 10/24. Container `h2r-opus26821` exited 0. No STOPPED file: it **finished normally**. The spend and disk stops never fired (80 GB free at the end).
- Cells: 90/90 without, 90/90 with (180/180).
- failure_class, without: solved 27, wrong_answer 53, hang 9, timeout 1 (1 checker timeout).
- failure_class, with: solved 20, wrong_answer 59, hang 10, timeout 1 (2 checker timeouts).
- Spend (sum of per-cell requests_cost_usd): without $44.93, with $40.02, **total $84.95**. The spend.log watcher's last reading was $84.20 at 179 cells. proxy-ledger/ has 180 per-cell request ledgers.
- an_a2.py (current, timeouts=env_failure): with 20/88 = 22.7%, without 27/89 = 30.3%, blocked 0 (SUMMARY-A2.txt).
- Pre-reg scoring (checker timeouts count as fail, nothing infra-dropped): with 20/90 = 22.2%, without 27/90 = 30.0%. The Researcher scores this formally.
- Transcripts (609 MB, 1,440 files, no single file over 50 MB) stay on the VM. They are listed with size and sha256 in MANIFEST-transcripts.txt, matching the h2-deferred-1023 convention.
- The prior 32/side partial is in results/h2-deferred-1023/opus/26821.
