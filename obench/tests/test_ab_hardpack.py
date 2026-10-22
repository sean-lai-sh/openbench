"""Opt-in hard-pack flags on thesis.ab.run_ab: defaults stay unchanged."""
import json
from pathlib import Path

from thesis.ab import run_ab

PACK = Path(__file__).resolve().parents[2] / "data" / "packs" / "openbench-tb-hard"


def test_defaults_unchanged():
    assert run_ab.CELL_TIMEOUT_CAP_S == 840
    assert run_ab.EXEC_MODE == "local"
    assert run_ab.CELL_META is None
    assert run_ab.cell_timeout(2400) == 840


def test_resolve_tasks_from_pack():
    names = run_ab.resolve_tasks(["dna-insert,video-processing"], PACK)
    assert names == ("dna-insert", "video-processing")
    assert len(run_ab.core_task_names(PACK)) == 9


def test_cell_meta_fields(tmp_path):
    spec = {"cell_path": str(tmp_path / "c.json"), "exec_mode": "docker",
            "cell_meta": {"vm_type": "n2-standard-16", "runner_commit": "abc",
                          "timeout_cap_s": 2400, "running_dir": str(tmp_path / ".running")}}
    run_ab.mark_running(spec, True)
    spec["concurrent_cells_at_start"] = 1
    row = {}
    run_ab.attach_cell_meta(row, spec, "2026-10-22T18:00:00+00:00")
    run_ab.mark_running(spec, False)
    assert row["vm_type"] == "n2-standard-16" and row["exec_mode"] == "docker"
    assert row["started_et"].startswith("2026-10-22T14:00:00")
    assert row["concurrent_cells_at_end"] == 1 and row["timeout_cap_s"] == 2400
    assert not list((tmp_path / ".running").iterdir())


def test_cell_meta_absent_by_default():
    row = {}
    run_ab.attach_cell_meta(row, {}, "2026-10-22T18:00:00+00:00")
    assert row == {}


def test_main_dry_run_hard_pack(tmp_path, monkeypatch):
    prs = tmp_path / "prs.csv"
    prs.write_text("#,PR,Title,Merged,Merge commit SHA,Parent/base SHA\n1,#1,t,2026,aaaa,bbbb\n")
    try:
        rc = run_ab.main([str(prs), "--tasks", "dna-insert", "--tasks-dir", str(PACK),
                          "--timeout-cap-s", "2400", "--exec", "docker", "--trials", "1",
                          "--out", str(tmp_path / "o"), "--dry-run"])
        assert rc in (0, 2)
        assert run_ab.CELL_TIMEOUT_CAP_S == 2400 and run_ab.EXEC_MODE == "docker"
    finally:
        run_ab.CELL_TIMEOUT_CAP_S = 840
        run_ab.EXEC_MODE = "local"
        run_ab.CELL_META = None
