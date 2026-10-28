# Pi smoke rerun on PR #134 (1e13ee95), 2026-10-25: failed in the Pi build

Run on thesis-h1-cpu, image h2-env:1022, PR worktree at /ob, metadata-server ADC. Command: `bash data/pi-harness-smoke/cell.sh /h2/pi-harness-smoke`. Two identical runs: pi-smoke-134b (21:18 EDT, run-134b.log) and pi-smoke-134c (22:40 EDT, run-134c.log).

- Both #136 fixes work: preflight passed (`import thesis` OK, `node --version` = v22.19.0, see wrapper-134c.log).
- New failure: `build_pi.compile_tree` -> `npm run build:offline` in packages/ai fails with TS2307 `Cannot find module './data/.manifest.json'`, plus follow-on TS2322 errors. At pin d0aa218c, `src/providers/data/.manifest.json` is not in the tree; it looks like a generated file (package.json has `generate-model-catalog`), so the build needs that step to run first, or the manifest needs to be vendored.

No model calls, $0 spend.
