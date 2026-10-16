# Oh My Pi trigger tasks: rows to tasks (rebuilt 2026-10-16)

16 tasks are in `tasks/`. 10 are copied from openbench main c8372a5 (merged in #23 and #27), and 6 were re-authored today after the 2026-10-16 restore (marked ★, not yet in any PR). Every task is unforced and prints `OBENCH_VERDICT` matching its exit code; `selftest.sh` checks fail, pass and echo for all 16 (see `selftest.log`). Detectors are in each task's DETECTORS.md.

| Row | PR / SHA (merge vs parent) | Change | Task | Status |
|---|---|---|---|---|
| 14 | direct, 687cf413 vs 3f3e696e | find: path folded into pattern; bare `*.ext` becomes recursive | ★ trig-omp-findext | awaiting screen |
| 15 | #13, 55f516b1 | drop "state intent before each tool call" | trig-omp-multistep | screened-null |
| 16 | 20663d0e | `<tools>` block in system prompt | trig-omp-multistep | **confirmed (efficiency)** |
| 17 | 27a1d25d | current date in system prompt | none (no dedicated task; size-only, multistep could carry it) | awaiting screen |
| 18 | 4a72bd65 | grep grouped output, limit 100→20 | trig-omp-callsites | awaiting screen |
| 19 | a95d432f | consolidated system prompt | trig-omp-multistep | null @30 (thinking off) |
| 20 | e4fa6aff | next hashline prompt variant | trig-omp-multiedit | not exercisable |
| 21 | 0dab29c0 | no estimates / unused-param rule | trig-omp-unusedparam | exercised-null |
| 22 | 3add2b8a | bash timeout-clamp notice | none | skipped |
| 23 | 2e6d96d3 vs 0d00f015 | read `N-` open-ended range | ★ trig-omp-tailread (smoke only) | awaiting screen |
| 24 | #1100, 2d96feb6 (diff on ^2) | `|` after hash is a separator | ★ trig-omp-mdtable | awaiting screen |
| 25 | c31daf08 vs 8a32eceb | find returns directories with `/` | ★ trig-omp-finddir | awaiting screen |
| 26 | 457fe9eb vs 829b999d | feat(coding-agent/prompts): routed parallel requests to task | trig-omp-fanout (inferred from title, unverified) | awaiting screen |
| 27 | #1808, 8596f08a vs efd66d9e | fix(search): default paths to workspace root instead of hard | trig-omp-callsites | awaiting screen |
| 28 | 9cd5c77c vs 52843e4f | subagent fan-out wording | trig-omp-fanout | screened-null (borderline) |
| 29 | eb8ed9c6 vs 4e54e557 | feat(coding-agent/prompts): enforced specialized tool usage  | trig-omp-callsites | awaiting screen |
| 30 | 213fdca7 vs bdfc21df | network-client guidance | trig-omp-netclient | screened-null (thinking off) |
| 31 | 63ff563e vs 5b026d30 | call-site guidance | trig-omp-callsites | screened-null (thinking off) |
| 32 | 69865b60 | verification guidelines | trig-omp-experiment | screened-null (thinking off) |
| 33 | 27e01998 | bash builtins inventory | trig-omp-multistep | screened-null |
| 34 | #8066, 949b251e | grep tool vs shell grep | trig-omp-callsites | awaiting screen |
| 35 | #8538, ca297741 | byte-stable system prompt | trig-omp-multistep | screened-null |
| 36 | ee4a1d48 | user-reported state is ground truth | trig-omp-reported | screened-null (data lost; rerun pending) |
| 37 | #9241, 5af88aea vs 70ce7585 | delete-safety scoped to unrelated code | ★ trig-omp-cutover | awaiting screen |
| 38 | 1b5c7b53 | testing guidance (fails pre-fix) | trig-omp-bugfix-regress | **confirmed (behavioural)** |
| 39 | #11209, 945d0ddd | bare-path image reads | trig-omp-image | screened-null |
| 40 | 6b620e56 vs da94b644 | dir read inline `… N more` cap | ★ trig-omp-dirread | awaiting screen |
| 41 | 051d3e13 | identity line rewording | trig-omp-multistep | awaiting screen |
| 42 | e25ed04f | bash utils list trimmed | trig-omp-multistep | awaiting screen |
| 43 | 6cb51f97 | read.md drops `?q=` | trig-omp-image | screened-null |
| 44 | #13113, d3e08e91 | dedupe system prompt rules | trig-omp-multistep | null @30 |
| 45 | #13333, 9985b638 | mid-stream stall recovery | none | skipped |

Full SHAs are in omp-triage.csv. Row 26 → fanout is inferred from its title ("routed parallel requests to task"); the original mapping was lost. Row 17 has no task.
