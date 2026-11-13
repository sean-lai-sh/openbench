"""Load OpenBench Hard suite lists and resolve task ids to task directories.

A suite file (TOML) lists its tasks in order, each with the bench snapshot it
comes from, a difficulty prior and the reason it was chosen::

    schema = "openbench.hard-suite/v1"
    name = "pilot"
    pool = "pilot-pool"                 # harder replacements (another suite file)

    [[task]]
    id = "dna-insert"
    source = "openbench-tb-hard"        # a key of SOURCES
    frontier_rate = 0.077               # published frontier-panel solve rate (lower = harder)
    domain = "bioinformatics / primer design"
    why = "..."

``SOURCES`` maps each source key to the in-repo tasks directory and the
upstream bench snapshot (repo + commit) its tasks were imported from. A task
id resolves to ``(tasks_dir, id)``, the pair ``obench.run.run_cell`` takes.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SUITE_SCHEMA = "openbench.hard-suite/v1"
SUITES_DIR = Path(__file__).with_name("suites")
REPO_ROOT = Path(__file__).resolve().parents[2]

TB2 = {"bench": "terminal-bench-2", "repo": "https://github.com/laude-institute/terminal-bench-2",
       "commit": "2fd12b88aafdd04a52c298e3940bcb189f9766d6",
       "rates": "harborframework/terminal-bench-2-leaderboard@572b2614be2c0cb2527e14f5b1e4026f1072e6c1"}

SOURCES = {
    "openbench-tb-hard": dict(TB2, tasks_dir="data/packs/openbench-tb-hard", pack="openbench/tb-hard@1.0.0"),
    "openbench-tb-mid": dict(TB2, tasks_dir="data/packs/openbench-tb-mid", pack="openbench/tb-mid@1.0.0"),
    "terminal-bench-2": dict(TB2, tasks_dir="tasks-imported/terminal-bench-2", pack=None),
}
REQUIRED_TASK_FILES = ("instruction.md", "checker.sh")


class SuiteError(ValueError):
    pass


@dataclass(frozen=True)
class Task:
    id: str
    source: str
    frontier_rate: float
    domain: str
    why: str

    @property
    def tasks_dir(self) -> Path:
        return REPO_ROOT / SOURCES[self.source]["tasks_dir"]

    @property
    def path(self) -> Path:
        return self.tasks_dir / self.id

    @property
    def bench(self) -> dict:
        return {k: SOURCES[self.source][k] for k in ("bench", "repo", "commit", "rates")}

    def difficulty_key(self) -> tuple:
        """Sort key, hardest first: lower published frontier rate is harder."""
        return (self.frontier_rate, self.id)


@dataclass(frozen=True)
class Suite:
    name: str
    tasks: tuple[Task, ...]
    pool: str | None
    planned_size: int

    def ids(self) -> list[str]:
        return [t.id for t in self.tasks]

    def task(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise SuiteError(f"{task_id!r} is not in suite {self.name!r}")


def _task(raw: dict, where: str) -> Task:
    missing = [k for k in ("id", "source", "frontier_rate", "domain", "why") if k not in raw]
    if missing:
        raise SuiteError(f"{where}: task is missing {missing}")
    if raw["source"] not in SOURCES:
        raise SuiteError(f"{where}: unknown source {raw['source']!r} (known: {sorted(SOURCES)})")
    rate = raw["frontier_rate"]
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0.0 <= rate <= 1.0:
        raise SuiteError(f"{where}: frontier_rate {rate!r} is not in [0, 1]")
    if not str(raw["why"]).strip():
        raise SuiteError(f"{where}: task {raw['id']!r} has no rationale")
    return Task(id=str(raw["id"]), source=raw["source"], frontier_rate=float(rate),
                domain=str(raw["domain"]), why=str(raw["why"]).strip())


def load_suite(name: str, suites_dir: Path = SUITES_DIR) -> Suite:
    path = Path(suites_dir) / f"{name}.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SUITE_SCHEMA:
        raise SuiteError(f"{path}: schema is {data.get('schema')!r}, expected {SUITE_SCHEMA}")
    tasks = tuple(_task(raw, f"{path}[{i}]") for i, raw in enumerate(data.get("task") or []))
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise SuiteError(f"{path}: duplicate task ids")
    return Suite(name=data.get("name", name), tasks=tasks, pool=data.get("pool"),
                 planned_size=int(data.get("planned_size", len(tasks))))


def resolve(task: Task) -> tuple[str, str]:
    """``(tasks_dir, task_id)`` for ``run_cell``; fails if the task directory
    is missing its instruction or checker."""
    missing = [f for f in REQUIRED_TASK_FILES if not (task.path / f).is_file()]
    if missing:
        raise SuiteError(f"task {task.id!r} at {task.path} is missing {missing}")
    return str(task.tasks_dir), task.id


def load_task(suite_name: str, task_id: str, suites_dir: Path = SUITES_DIR) -> tuple[str, str]:
    """Load one task by id from a suite: ``(tasks_dir, task_id)``."""
    return resolve(load_suite(suite_name, suites_dir).task(task_id))
