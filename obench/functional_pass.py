"""Secondary ``functional_pass`` for polyglot-rust-c, from a saved workspace.

The primary checker score is unchanged. For this one task, ``functional_pass``
is that same checker run again inside the task image with only the
"/app/polyglot contains only main.rs" assertion removed. Compilation and the
Fibonacci cases stay. Every other task is null. The agent is not run again.
"""

import os
import shutil
import tempfile

from .paths import docker_workdir_parent

POLYGLOT_TASK = "polyglot-rust-c"

# The only check functional_pass skips. Matched exactly, once, so a drift in
# the checker fails closed (null) instead of dropping some other assertion.
_ONLY_MAIN_RS_CHECK = (
    "    # Verify that only main.rs exists in /app/polyglot\n"
    "    polyglot_files = os.listdir(\"/app/polyglot\")\n"
    "    print(polyglot_files)\n"
    "    assert polyglot_files == [\"main.rs\"], (\n"
    "        f\"Expected only main.rs, found: {polyglot_files}\"\n"
    "    )\n"
)

_SKIP_NOTE = "    # functional_pass: only-main.rs directory check skipped.\n"


def strip_only_main_rs_check(source):
    """Return ``source`` without the only-main.rs assertion, or None.

    None means the check was missing or repeated, so it cannot be skipped
    alone. Callers leave ``functional_pass`` null in that case.
    """
    if not isinstance(source, str) or source.count(_ONLY_MAIN_RS_CHECK) != 1:
        return None
    return source.replace(_ONLY_MAIN_RS_CHECK, _SKIP_NOTE, 1)


def stage_functional_task(task_dir):
    """Copy ``task_dir`` with only the only-main.rs check removed.

    The copy is staged where a docker bind mount can see it. Returns None
    when that one check cannot be isolated. The caller's task tree is not
    modified.
    """
    test_py = os.path.join(
        task_dir, "checker_data", "harbor-tests", "test_outputs.py")
    try:
        with open(test_py, encoding="utf-8") as fh:
            source = fh.read()
    except OSError:
        return None
    patched = strip_only_main_rs_check(source)
    if patched is None:
        return None
    staged = tempfile.mkdtemp(
        prefix="obench-functional-task-", dir=docker_workdir_parent())
    try:
        shutil.copytree(task_dir, staged, symlinks=True, dirs_exist_ok=True)
        out = os.path.join(
            staged, "checker_data", "harbor-tests", "test_outputs.py")
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(patched)
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return staged


def run_functional_checker(task, workdir, task_dir, task_image,
                           container_workdir="/app", timeout_s=120):
    """Rerun the polyglot checker on a copy of ``workdir``.

    Returns ``(checker_exit, stdout, stderr)``, or None when this task has
    no functional grade (not polyglot-rust-c, no task image, or the single
    directory check cannot be isolated). The copy is discarded, so the saved
    workspace is not modified. ``stdout``/``stderr`` are the checker's.
    """
    if task != POLYGLOT_TASK or not task_image:
        return None
    if not workdir or not os.path.isdir(workdir):
        return None
    staged = stage_functional_task(task_dir)
    if staged is None:
        return None
    parent = docker_workdir_parent()
    copy = tempfile.mkdtemp(prefix="obench-functional-ws-", dir=parent)
    try:
        shutil.copytree(workdir, copy, symlinks=True, dirs_exist_ok=True)
        from .run import run_checker
        exit_code, _raw_score, stdout, stderr = run_checker(
            staged, copy, timeout_s, task_image=task_image,
            container_workdir=container_workdir or "/app",
        )
        return exit_code, stdout, stderr
    finally:
        shutil.rmtree(staged, ignore_errors=True)
        shutil.rmtree(copy, ignore_errors=True)


def functional_pass(task, workdir, task_dir, task_image,
                    container_workdir="/app", timeout_s=120):
    """Return 1, 0, or None for one saved workspace.

    1 and 0 are checker verdicts. None means the secondary grade does not
    apply, or the checker did not grade (timeout, missing image, launch
    failure). None is not a fail.
    """
    result = run_functional_checker(
        task, workdir, task_dir, task_image,
        container_workdir=container_workdir, timeout_s=timeout_s,
    )
    if result is None:
        return None
    exit_code, _stdout, _stderr = result
    from .run import checker_run_was_defect
    if checker_run_was_defect(exit_code):
        return None
    return 1 if exit_code == 0 else 0
