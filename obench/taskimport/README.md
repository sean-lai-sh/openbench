# Task import pipeline (SEA-106)

Imports external benchmark tasks into OpenBench's task format and admits only
those that pass `obench validate`-style polarity with **no network**: the
untouched workspace must fail and the solution must pass. Docker runs on the
GCP VM, never on the Mac mini.

| Source (priority order) | Pin | Format |
|---|---|---|
| Tasks already in the repo | — | kept as they are; any duplicate is skipped |
| Terminal-Bench 2 | `laude-institute/terminal-bench-2` @ `2fd12b88aafdd04a52c298e3940bcb189f9766d6` | Harbor |
| Terminal-Bench 1 core 0.1.1 | `laude-institute/terminal-bench` @ `91e10457b5410f16c44364da1a34cb6de8c488a5`, `./tasks` (80 ids in `registry.json`) | TB1, converted by `tb1_to_harbor.py` |
| Terminal-Bench Pro 1.0 | `alibaba/terminal-bench-pro` @ `82bc46de337f48d57a5d78f4900ce7eabc485101` | Harbor |

Dedupe (`plan`) works in that order, by task name **and** by normalized
instruction text. A TB Pro task that duplicates TB2 or TB1 core (or anything
already in the repo) is removed, and the report lists it with what it
duplicates. Each source is reported as its own group.

## What each imported task gets

- `workspace/`: the environment image's WORKDIR at the start.
- `checker_data/image/Dockerfile`: the task image, `FROM` the pinned
  environment (a pulled image pinned by repo digest, or a built image recorded
  by id with base-image digests). It primes the verifier's dependencies by
  running upstream `tests/test.sh` once at build time with network, then sets
  `UV_OFFLINE=1 PIP_NO_INDEX=1`. The agent and the checker both use this image
  (`task.toml` `docker_image` and `docker_image_id`), as in the
  openbench-tb-mid pack.
- `checker.sh`: runs upstream `tests/test.sh` with `--network none`. The
  reward is `/logs/verifier/reward.txt`. With the solution overlay it first
  runs upstream `solve.sh` (`checker_data/oracle/`).
- `task.toml` (image, workdir, checker and agent timeouts, upstream pin) and
  `PROVENANCE.md`.

**Drop-outs** go to `<out>/_dropped/<source>/<task>/`, each with stage and reason:
- GPU tasks;
- multi-container TB1 tasks and interactive TB1 solutions (converter);
- an image that can't be pulled or built, or that has no WORKDIR;
- the workspace already passes;
- the solution fails. When the output shows network errors the reason is
  "verifier or oracle needs network".

**Known limitation:** only WORKDIR carries from the agent's run to the
checker, the same as the existing TB2 imports. A task graded on system state
the agent changed outside WORKDIR is graded on a fresh container.

## Run on the VM

```bash
cd ~/openbench && git fetch origin && git checkout sea-106/import-pipeline
python3 -m pip install --user pyyaml            # TB1 task.yaml / solution.yaml
SRC=$HOME/import-src && mkdir -p $SRC

# 1. Upstream checkouts at the pins
git clone https://github.com/laude-institute/terminal-bench-2 $SRC/tb2 && git -C $SRC/tb2 checkout 2fd12b88aafdd04a52c298e3940bcb189f9766d6
git clone https://github.com/laude-institute/terminal-bench $SRC/tb1 && git -C $SRC/tb1 checkout 91e10457b5410f16c44364da1a34cb6de8c488a5
git clone https://github.com/alibaba/terminal-bench-pro $SRC/tbpro && git -C $SRC/tbpro checkout 82bc46de337f48d57a5d78f4900ce7eabc485101
curl -fsSL https://raw.githubusercontent.com/laude-institute/terminal-bench/main/registry.json -o $SRC/tb1-registry.json

# 2. TB1 core -> Harbor (80 ids; refusals listed in convert-report.json)
python3 -m obench.taskimport.tb1_to_harbor --src $SRC/tb1/tasks --registry $SRC/tb1-registry.json --out $SRC/tb1-harbor

# 3. Plan with dedupe (priority: repo, TB2, TB1 core, TB Pro)
python3 -m obench.taskimport.pipeline plan --repo-root . --out $SRC/plan.json \
  --source "terminal-bench-2=$SRC/tb2@https://github.com/laude-institute/terminal-bench-2@2fd12b88aafdd04a52c298e3940bcb189f9766d6" \
  --source "terminal-bench-core=$SRC/tb1-harbor@https://github.com/laude-institute/terminal-bench@91e10457b5410f16c44364da1a34cb6de8c488a5" \
  --source "terminal-bench-pro=$SRC/tbpro@https://github.com/alibaba/terminal-bench-pro@82bc46de337f48d57a5d78f4900ce7eabc485101"

# 4. Import + no-network validation (Docker; resumable: re-run to continue, --retry to redo)
python3 -m obench.taskimport.pipeline run --plan $SRC/plan.json --out tasks-imported --report $SRC/import-report.jsonl
#    smoke two tasks first:  ... run ... --only bn-fit-modify build-cython-ext

# 5. Per-source report (goes into the imports data PR with tasks-imported/ and plan.json)
python3 -m obench.taskimport.pipeline report --plan $SRC/plan.json --report $SRC/import-report.jsonl --out $SRC/IMPORT_REPORT.md
```

If the TB Pro checkout keeps its tasks in a subdirectory, point the
`terminal-bench-pro` root at that directory: the directory that directly
holds the task folders, each with `task.toml` and `instruction.md`. Harbor's
registry lists Pro task paths at the repo root.
