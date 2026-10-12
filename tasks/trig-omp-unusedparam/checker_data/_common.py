import os, subprocess, sys, traceback, shutil, tempfile
from pathlib import Path
TASK_DIR = Path(os.environ["TASK_DIR"])
def verdict(ok, msg):
    print(msg if ok else msg, file=sys.stdout if ok else sys.stderr)
    print("OBENCH_VERDICT: " + ("pass" if ok else "fail"))
    return 0 if ok else 1
def run_hidden_tests(test_dir_name="hidden_tests"):
    """Copy the checker's own tests into a temp dir and run them against the workspace code."""
    tmp = Path(tempfile.mkdtemp(prefix="obench-hidden-"))
    try:
        for f in (TASK_DIR / "checker_data" / test_dir_name).iterdir():
            shutil.copy(f, tmp / f.name)
        env = dict(os.environ, PYTHONPATH=os.getcwd() + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp)], env=env, capture_output=True, text=True, timeout=300)
        return p.returncode, (p.stdout + p.stderr)[-3000:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
def entry(main):
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
