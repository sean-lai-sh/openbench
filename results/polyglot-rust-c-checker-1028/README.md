# polyglot-rust-c checker check (2026-10-28, $0, no model calls)

Pack files are byte-identical to main 65f1c985 (sha256 values are in the log). Ran on thesis-h1-cpu. The VM worktree was at 1edba44a, and the pack has the same hashes there.

## Reference solution (`solution/polyglot/main.rs`) through `checker.sh`
| Where | Command | Result |
|---|---|---|
| B: inside image h1-env:1027-strace | `docker run --rm -v $T:/task:ro -v $W:/work -w /work -e TASK_DIR=/task h1-env:1027-strace bash /task/checker.sh` | **PASS**, exit 0. `1 passed`. rustc 1.63.0, g++ 12.2.0 |
| A: host-side, the same way `obench/run.py::run_checker` invokes it (cwd=workspace, TASK_DIR) | `cd $W && TASK_DIR=$T bash $T/checker.sh` | **FAIL**, exit 1. `/bin/sh: 1: rustc: not found` and then `FileNotFoundError .../polyglot/main` |

The checker logic is sound. It accepts a known-good answer when it runs in the task image.

## Why both bridge cells (pi-harness-bridge-smoke-1028c/attempt2-metadata-adc) got wrong_answer
Both are harness/env defects. Neither is a genuine agent miss.
1. **The answer path never reached the workspace.** The instruction says `/app/polyglot/main.rs`. Docker cells mount the workspace at `/work` (obench/docker_exec.py). The `/app` to workspace rewrite (run.py ~2137) applies only when `exec_mode=="local"` and `OBENCH_HARBOR_APP_REWRITE=1`. Both agents wrote a working polyglot to `/app/polyglot/main.rs` inside the container. Pi's transcript shows both compilers printing 89 for n=10. OpenCode's shows `1 1 2 89 4660046610375530309` from both. That file was discarded. The checker then saw only `.gitkeep` (workspace_changed=False), which gives `FileNotFoundError .../polyglot`.
2. **The checker runs on the host, not in the task image.** run_checker uses host `subprocess.Popen`. This checker.sh never uses `BENCH_TASK_IMAGE`/docker, and the VM host has no rustc. So even a correct file in the workspace would fail (run A above).

Fix direction (not applied): apply the `/app` rewrite for docker-mode harbor tasks (or mount the workspace at /app), and run the checker for this task inside `BENCH_TASK_IMAGE`.
