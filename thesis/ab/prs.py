"""PR list boundary. CSV columns are read by header name."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from thesis.ab.harness import harness_name


class PrListError(ValueError):
    """The PR file is not a usable list."""


class Side(Enum):
    WITHOUT = "without"
    WITH = "with"


_SHA = re.compile(r"^[0-9a-f]{40}$")
_PR = re.compile(r"^[A-Za-z0-9._-]+$")

PRIMARY_WITH = "Merge commit SHA"
PRIMARY_WITHOUT = "Parent/base SHA"
PRIMARY_PR = "PR"


@dataclass(frozen=True)
class PullRequest:
    pr: str
    title: str
    merged: str
    with_sha: str
    without_sha: str
    nearest_release: str
    category: str
    files_changed: str
    key_paths: str
    one_line: str
    harness_change: str
    bugfix_check: str
    repo: str = ""
    number: str = ""

    def sha_for(self, side: Side) -> str:
        if side is Side.WITHOUT:
            return self.without_sha
        return self.with_sha


def _sha(raw: str, source: str) -> str:
    text = (raw or "").strip().lower()
    if not _SHA.fullmatch(text):
        raise PrListError(f"{source}: expected a 40-character SHA, got {raw!r}")
    return text


def _pr(raw: str, source: str) -> str:
    text = (raw or "").strip()
    if not text or not _PR.fullmatch(text) or "/" in text or "\\" in text:
        raise PrListError(f"{source}: expected a PR id, got {raw!r}")
    return text


def _cell(row: dict, *names: str) -> str:
    for name in names:
        if name in row and row[name] is not None:
            return str(row[name]).strip()
    return ""


def _identity(row: dict, source: str) -> tuple[str, str, str]:
    repo = _cell(row, "Repo", "repo")
    number = _cell(row, "#", "number")
    if not repo:
        return "", "", number
    try:
        name = harness_name(repo)
    except KeyError:
        raise PrListError(f"{source}: unknown repo {repo!r}") from None
    if not number.isdigit():
        raise PrListError(f"{source}: expected a row number in #, got {number!r}")
    return f"{name}-{int(number)}", repo, str(int(number))


def _from_primary(row: dict, source: str) -> PullRequest:
    run_id, repo, number = _identity(row, source)
    return PullRequest(
        pr=run_id or _pr(_cell(row, PRIMARY_PR), f"{source} PR"),
        title=_cell(row, "Title"),
        merged=_cell(row, "Merged"),
        with_sha=_sha(_cell(row, PRIMARY_WITH), f"{source} {PRIMARY_WITH}"),
        without_sha=_sha(_cell(row, PRIMARY_WITHOUT), f"{source} {PRIMARY_WITHOUT}"),
        nearest_release=_cell(row, "Nearest release tag"),
        category=_cell(row, "Category"),
        files_changed=_cell(row, "Files changed"),
        key_paths=_cell(row, "Key paths"),
        one_line=_cell(row, "One-line behavior change"),
        harness_change=_cell(row, "Harness change"),
        bugfix_check=_cell(row, "Bug-fix check"),
        repo=repo,
        number=number,
    )


def _from_fallback(row: dict, source: str) -> PullRequest:
    run_id, repo, number = _identity(row, source)
    return PullRequest(
        pr=run_id or _pr(_cell(row, "pr"), f"{source} pr"),
        title=_cell(row, "title", "Title"),
        merged=_cell(row, "merged", "Merged"),
        with_sha=_sha(_cell(row, "after_sha"), f"{source} after_sha"),
        without_sha=_sha(_cell(row, "before_sha"), f"{source} before_sha"),
        nearest_release=_cell(row, "nearest_release", "Nearest release tag"),
        category=_cell(row, "category", "Category"),
        files_changed=_cell(row, "files_changed", "Files changed"),
        key_paths=_cell(row, "key_paths", "Key paths"),
        one_line=_cell(row, "one_line", "One-line behavior change"),
        harness_change=_cell(row, "harness_change", "Harness change"),
        bugfix_check=_cell(row, "bugfix_check", "Bug-fix check"),
        repo=repo,
        number=number,
    )


def _is_primary(fieldnames: list[str] | None) -> bool:
    names = set(fieldnames or [])
    return PRIMARY_PR in names and PRIMARY_WITH in names and PRIMARY_WITHOUT in names


def _load_rows(path: Path) -> tuple[list[dict], list[str] | None, bool]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl" or text.lstrip().startswith("{"):
        rows = []
        for lineno, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PrListError(f"{path}:{lineno}: {exc}") from exc
            if not isinstance(item, dict):
                raise PrListError(f"{path}:{lineno}: expected an object")
            rows.append(item)
        return rows, None, False
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise PrListError(f"{path}: missing header row")
    return list(reader), list(reader.fieldnames), _is_primary(list(reader.fieldnames))


def parse_prs(path: Path) -> tuple[PullRequest, ...]:
    """Load a primary CSV, a fallback CSV, or a fallback JSONL file."""
    path = Path(path)
    if not path.is_file():
        raise PrListError(f"PR list not found: {path}")
    rows, _fields, primary = _load_rows(path)
    if not rows:
        raise PrListError(f"{path}: no PR rows")
    found: list[PullRequest] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        source = f"{path}:{index + 1}"
        if primary:
            item = _from_primary(row, source)
        else:
            item = _from_fallback(row, source)
        if item.pr in seen:
            raise PrListError(f"{source}: duplicate PR {item.pr}")
        seen.add(item.pr)
        found.append(item)
    return tuple(found)


def select_prs(rows: tuple[PullRequest, ...], wanted: list[str] | None) -> tuple[PullRequest, ...]:
    if not wanted:
        return rows
    ids: list[str] = []
    for chunk in wanted:
        for piece in chunk.split(","):
            text = piece.strip()
            if text:
                ids.append(text)
    missing = [item for item in ids if item not in {row.pr for row in rows}]
    if missing:
        raise PrListError(f"unknown PR id(s): {', '.join(missing)}")
    chosen = {item for item in ids}
    return tuple(row for row in rows if row.pr in chosen)
