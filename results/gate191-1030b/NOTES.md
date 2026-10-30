# #191 regate, 2026-10-30 (b): FAIL on the `with` row (checker timeout). Cause is a port collision between the two concurrent checkers, not the venv

- **Runner:** #191 head `b43e88d1c33d81513eb32f0aa9cbd42ba74057d6` (cursor/checker-timeout-fix). Includes `final_workspace_status`.
- **Cell:** Opus (claude-opus-5-5), PR 4204, torch-tensor-parallelism, trial 1, both sides. Run with `--jobs 2` and `--network host`, the same as gate #198.
- **Agent image:** h1-env:1022, `sha256:3ef8e823e1894922c4569180eb358f63f85a33bcfe1aecdadc45aaa81331b224`.
- **Checker venvs:** `h2-checker-venvs:b43e88d1`, image id `sha256:03af82dde94a5c5fae0d8a17dbece9322b7a0b89fa68bd214f65c42c02c41997`. Rebuilt on thesis-h1-cpu from thesis/ab/h2env at b43e88d1 and also tagged `:latest`. The extracted stage is 3.2G.
- **Driver:** `driver/gate191b.sh`. It follows the repo's h2.sh pattern: extract the stage, run the spend self-test, run the torch probe, then the same docker run env and mounts. It restricts the run to a single cell, like `driver/run1.sh`.

## Pre-checks (all passed)
| check | without (0d3d48bb) | with (963a926d) |
|---|---|---|
| sha256 | 12d778e4…31a1 (matches #198) | b44f4f23…6f61 (matches #198) |
| mtime (UTC) | 2026-10-17T02:12:25Z (matches) | 2026-10-17T02:12:06Z (matches) |
| `--version` | 0.0.0--202610170212 | 0.0.0--202610170212 |
| row harness_version | 0.0.0--202610170212 (host) | 0.0.0--202610170212 (host) |

- binary_hash_source=post_hoc_disk and binary_source=original. The runner does not write these on the row, so they are recorded here.
- Spend self-test: `spend self-test PASS: 2 cells, $0.3708 (expect $0.3708)`.
- Venv preflight inside h1-env:1022 (`attach_checker_venvs` then `verify_split_checker_venv`) passed for all 9 tasks. Every bin/python resolves to `.uv-python/cpython-3.13.9` inside the artifact; sam-cell-seg uses 3.11.14. See `driver/preflight.log`.

## Result (gate run 17:02 to 17:14 ET)
| criterion | without | with |
|---|---|---|
| checker under 600 s with a real verdict | 39.1 s, wrong_answer (6 failed, 7 passed) | **612.3 s, checker_timeout (FAIL)** |
| no uv download or "Installed" lines | none | none |
| time limit recorded | checker_timeout_s=600, timeout_s=2400 | same |
| agent image h1-env:1022 | yes | yes |
| free_disk_gb | 33.73 | 33.78 |
| workspace tarball and sha256 | saved, 28f306e8…1e10 (sha256 verified on disk) | saved, c95bcdd5…a21b (sha256 verified on disk) |
| spend | $0.1886 | $0.2765 |

Total spend was **$0.4651**, under the $5 stop. The spend watcher tracked the cells correctly during the run.

## Why the `with` checker timed out
- Both checkers ran at the same time. The `with` checker ran from 17:03:3x to 17:13:44 ET; the `without` checker ran from about 17:03:37 to 17:04:16 ET.
- Both used `--network host`, and test_outputs.py uses the fixed torch.distributed port 12355.
- The `without` checker logged `EADDRINUSE ... port: 12355`. Its six failing tests are the world-size-2 and world-size-4 cases, so its verdict is contaminated too.
- The `with` checker then hung until the 600 s cap.
- The venv and install path is fixed: no downloads, and the interpreters resolve.
- Fix options:
  - Serialize checkers for tasks that bind ports, or run with `--jobs 1`.
  - Give each checker its own network namespace or MASTER_PORT.

## Other observations
- run.log reports `cell missing required fields ['probe_method','provider_loaded_version','cell_image','build_channel','runner_commit']` for both cells.

## Files
- `out/`: cells, transcripts and workspace tarballs. No file is over 50 MB, so there is no MANIFEST.
- `driver/`: the driver, run1.sh, driver.log (spend log inline), build.log, preflight.log, selftest.log.
- `compile/`: researcher check (b). Contains the `uv pip compile` outputs per batch date and lockfiles read from the dist-info METADATA in the image venvs.

## Off-protocol marking (2026-10-30, 5:25 PM ET)
Both rows (`gate-row.json` and the two cell JSONs) are marked `off_protocol=true` with `gate_fail_reason=port_collision`. The two checkers ran at the same time on host networking and both used torch.distributed port 12355. The `without` checker hit EADDRINUSE and the `with` checker timed out. Neither verdict counts.
