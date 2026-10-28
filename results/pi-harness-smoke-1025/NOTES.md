# Pi smoke on PR #134 (2928b149), 2026-10-25: did not reach a cell

Run on thesis-h1-cpu in image h2-env:1022, with the PR branch worktree mounted at /ob, metadata-server ADC (OBENCH_ADC_METADATA=1) and GOOGLE_CLOUD_PROJECT set. Command: `bash data/pi-harness-smoke/cell.sh /h2/pi-harness-smoke`.

1. Attempt 1 (19:46 EDT, run-attempt1-nopythonpath.log) failed with `ModuleNotFoundError: No module named 'thesis'`. `pip install -e /ob` only packages `obench*`, and `python data/.../cell.py` puts the script directory on sys.path, not /ob. cell.sh needs `PYTHONPATH=/ob`, or it should run as a module.
2. Attempt 2 (with `-e PYTHONPATH=/ob`, run.log) cloned the pin d0aa218c and then failed in `build_pi.binary` -> `toolchain.ensure_node` with `/root/.nvm/nvm.sh: No such file or directory`. h2-env:1022 has no nvm, so Pi can't be built in this image.

No model calls were made and spend is $0. Credentials were never exercised.
