ENOENT-set smoke #4838 PASS @ 019ad6e (PR #8 packaging)

Worktree /workspace/openbench-ab detached @ 019ad6e. Rebuilt parent ff609a52 + merge aaa31f02 (wiped prior musl bins); both host-runnable (glibc interp).

Numbers (Researcher scoring lock — report only, no clear claim):
- pass 1.000 → 1.000 (n=24/24)
- wall 51.4s → 53.7s (+4.5%)
- tok/cell 181k → 221k (+21.6%)
- out tokens / non-cache input: see smoke-4838.md (proxy_measured on all 48)
- $ secondary: $/cell 0.258 → 0.253 (−1.7%); PR$ ~12.27
- CR=0; launched 48; exit 0; wall ~8m (17:04–17:12 ET)
- spend est. $464 → $477; soft pause $700

Paths: results/ab-logs/smoke-4838.md, results/ab/4838/

Proceeding to remaining ENOENT set: 4204, 5066, 5131, 5140, 5527, 6524 (3 trials / jobs 8).
