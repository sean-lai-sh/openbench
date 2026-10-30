# Which image the H2 hard-suite 1022 batch used

The record of the image that actually ran is `results/h2-hardsuite-1022/driver.log`:
its start line says `image=h2-env:1022(sha256:72c59033…)`.

- `h2.sh` / `run1.sh` reproduce that batch: container image `h2-env:1022`
  (built by `Dockerfile.h2` FROM h1-env:1022 plus a warm uv cache), restored from
  the launcher copies on thesis-h1-cpu:~/h2. The one addition is
  `OBENCH_AGENT_IMAGE` (and `OBENCH_AGENT_IMAGE_DIGEST`), so a rerun fills
  `cell_image` on every row. The original run did not set it, which is why the
  1022 rows have a null image digest.
- `h2-h1env.sh` / `run1-h1env.sh` are the later #191 rewrite (unmodified
  h1-env:1022 plus mounted h2-checker-venvs, spend-monitor self-test, torch probe).
  The 1022 batch did not use them. They stay for the gate191-style batches that
  follow that pattern (results/gate191-1030b/NOTES.md).
