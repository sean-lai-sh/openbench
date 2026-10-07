from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from pathlib import Path

from thesis.ab.prs import AA_SIDES, PullRequest, Side, parse_prs

EXCLUDED = frozenset({"infra", "rate_limited", "stalled"})
TOKEN_FIELDS = (
    "tokens_input_uncached",
    "tokens_output",
    "tokens_cache_read",
    "tokens_cache_write",
)
RATES = {
    "tokens_input_uncached": 4.0,
    "tokens_output": 20.0,
    "tokens_cache_read": 0.20,
    "tokens_cache_write": 5.0,
}


_PROXY_FIELDS = (
    "tokens_proxy_input_uncached",
    "tokens_proxy_output",
    "tokens_proxy_cache_read",
    "tokens_proxy_cache_write",
)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def billable_tokens(row: dict) -> dict[str, float] | None:
    vendor = [_number(row.get(field)) for field in TOKEN_FIELDS]
    if all(value is not None for value in vendor) and any(value > 0 for value in vendor):
        return dict(zip(TOKEN_FIELDS, vendor))
    if row.get("token_basis_proxy") == "proxy_measured":
        proxy = [_number(row.get(field)) for field in _PROXY_FIELDS]
        if all(value is not None for value in proxy):
            return dict(zip(TOKEN_FIELDS, proxy))
    if all(value is not None for value in vendor):
        return dict(zip(TOKEN_FIELDS, vendor))
    return None


def row_cost(row: dict) -> float | None:
    """USD for one cell. None when the token split is incomplete."""
    split = billable_tokens(row)
    if split is None:
        return None
    total = 0.0
    for field, rate in RATES.items():
        total += (split[field] / 1_000_000.0) * rate
    return total


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def countable(row: dict) -> bool:
    return row.get("failure_class") not in EXCLUDED


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def side_stats(rows: list[dict]) -> dict:
    kept = [row for row in rows if countable(row)]
    passed = [row for row in kept if row.get("success") is True]
    scores = [float(row["score"]) for row in kept if isinstance(row.get("score"), (int, float))]
    times = [float(row["wall_time_s"]) for row in kept if isinstance(row.get("wall_time_s"), (int, float))]
    tokens = []
    for row in kept:
        total = _token_total(row)
        if total is not None:
            tokens.append(total)
    n = len(kept)
    return {
        "n": n,
        "pass_rate": (len(passed) / n) if n else None,
        "mean_score": _mean(scores),
        "median_time_s": _median(times),
        "mean_tokens": _mean(tokens),
    }


def _score(row: dict) -> float | None:
    return _number(row.get("score"))


def _wall_time(row: dict) -> float | None:
    return _number(row.get("wall_time_s"))


def _turns(row: dict) -> float | None:
    return _number(row.get("turns"))


def _token_total(row: dict) -> float | None:
    split = billable_tokens(row)
    if split is None:
        return None
    return sum(split.values())


TASK_DELTAS = (
    ("time_s", "Time s", _wall_time, 3),
    ("turns", "Turns", _turns, 3),
    ("tokens", "Tokens", _token_total, 1),
    ("cost_usd", "Cost USD", row_cost, 3),
)


def task_samples(rows: list[dict], value_of) -> dict[str, list[float]]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        if not countable(row):
            continue
        value = value_of(row)
        if value is None:
            continue
        buckets.setdefault(str(row.get("task")), []).append(value)
    return buckets


def task_score_means(rows: list[dict]) -> dict[str, float]:
    return {
        task: sum(values) / len(values)
        for task, values in task_samples(rows, _score).items()
    }


def task_pass_rates(rows: list[dict]) -> dict[str, float]:
    totals: dict[str, int] = {}
    hits: dict[str, int] = {}
    for row in rows:
        if not countable(row):
            continue
        task = str(row.get("task"))
        totals[task] = totals.get(task, 0) + 1
        if row.get("success") is True:
            hits[task] = hits.get(task, 0) + 1
    return {task: hits.get(task, 0) / count for task, count in totals.items() if count}


def paired_deltas(without_rows: list[dict], with_rows: list[dict]) -> list[float]:
    left = task_score_means(without_rows)
    right = task_score_means(with_rows)
    return [right[task] - left[task] for task in sorted(set(left) & set(right))]


def _percentile_interval(samples: list[float]) -> tuple[float, float]:
    draws = len(samples)
    lo = samples[int(0.025 * (draws - 1))]
    hi = samples[min(draws - 1, int(round(0.975 * (draws - 1))))]
    return (lo, hi)


def bootstrap_ci(deltas: list[float], draws: int = 1000, seed: int = 0) -> tuple[float, float] | None:
    """Percentile interval of the mean, resampling tasks with replacement."""
    if not deltas:
        return None
    rng = random.Random(seed)
    k = len(deltas)
    means = []
    for _ in range(draws):
        sample = [deltas[rng.randrange(k)] for _ in range(k)]
        means.append(sum(sample) / k)
    means.sort()
    return _percentile_interval(means)


def bootstrap_mean_diff(
    left: list[float], right: list[float], draws: int = 1000, seed: int = 0,
) -> tuple[float, float] | None:
    if not left or not right:
        return None
    rng = random.Random(seed)
    n = len(left)
    m = len(right)
    diffs = []
    for _ in range(draws):
        left_mean = sum(left[rng.randrange(n)] for _ in range(n)) / n
        right_mean = sum(right[rng.randrange(m)] for _ in range(m)) / m
        diffs.append(right_mean - left_mean)
    diffs.sort()
    return _percentile_interval(diffs)


def _paired_metric(without_rows: list[dict], with_rows: list[dict], value_of) -> dict[str, dict]:
    left = task_samples(without_rows, value_of)
    right = task_samples(with_rows, value_of)
    paired = {}
    for task in set(left) & set(right):
        paired[task] = {
            "delta": (sum(right[task]) / len(right[task])) - (sum(left[task]) / len(left[task])),
            "ci": bootstrap_mean_diff(left[task], right[task]),
        }
    return paired


def task_metric_deltas(without_rows: list[dict], with_rows: list[dict]) -> list[dict]:
    computed = [
        (key, digits, _paired_metric(without_rows, with_rows, value_of))
        for key, _label, value_of, digits in TASK_DELTAS
    ]
    names: set[str] = set()
    for _key, _digits, paired in computed:
        names.update(paired)
    rows = []
    for task in sorted(names):
        metrics = {}
        for key, digits, paired in computed:
            found = paired.get(task)
            metrics[key] = {
                "delta": None if found is None else found["delta"],
                "ci": None if found is None else found["ci"],
                "digits": digits,
            }
        rows.append({"task": task, "metrics": metrics})
    return rows


def headroom_report(without_rows: list[dict], with_rows: list[dict]) -> dict:
    left_score = task_score_means(without_rows)
    right_score = task_score_means(with_rows)
    left_pass = task_pass_rates(without_rows)
    right_pass = task_pass_rates(with_rows)
    tasks = []
    deltas = []
    for task in sorted(set(left_score) & set(right_score)):
        if left_score[task] >= 1.0 and right_score[task] >= 1.0:
            continue
        tasks.append({
            "task": task,
            "without_score": left_score[task],
            "with_score": right_score[task],
            "without_pass_rate": left_pass.get(task),
            "with_pass_rate": right_pass.get(task),
        })
        if task in left_pass and task in right_pass:
            deltas.append(right_pass[task] - left_pass[task])
    return {
        "tasks": tasks,
        "delta_pass_rate": _mean(deltas),
        "delta_ci": bootstrap_ci(deltas),
        "n": len(deltas),
    }


def _fmt(value, digits=3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _ci_text(ci, digits=3) -> str:
    if ci is None:
        return ""
    return f"{ci[0]:.{digits}f} to {ci[1]:.{digits}f}"


def _task_word(n: int) -> str:
    return "task" if n == 1 else "tasks"


SDK_CHANGED = "SDK changed: harness delta may be confounded"
_TOOLCHAIN_KEYS = ("ai", "anthropic", "bun")


def toolchain_from(body) -> dict:
    if not isinstance(body, dict):
        return {}
    parsed = {}
    for key in _TOOLCHAIN_KEYS:
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            parsed[key] = value.strip()
    return parsed


def _load_toolchain(root: Path, side: str, rows: list[dict]) -> dict:
    path = root / f"{side}.toolchain.json"
    if path.is_file():
        try:
            return toolchain_from(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            return {}
    for row in rows:
        found = toolchain_from(row.get("toolchain") if isinstance(row, dict) else None)
        if found:
            return found
    return {}


def sdk_versions_differ(left: dict, right: dict) -> bool:
    without = left.get("anthropic")
    with_side = right.get("anthropic")
    return bool(without and with_side and without != with_side)


def _side_files(root: Path, side: str) -> bool:
    if (root / f"{side}.jsonl").is_file():
        return True
    return any((root / f"{side}.{kind}.json").is_file() for kind in ("incompatible", "infra"))


def _load_named_side(root: Path, side: str) -> tuple[list[dict], dict | None]:
    verdict = None
    for kind in ("incompatible", "infra"):
        path = root / f"{side}.{kind}.json"
        if path.is_file():
            verdict = json.loads(path.read_text(encoding="utf-8"))
            break
    rows = [] if verdict is not None else load_jsonl(root / f"{side}.jsonl")
    return rows, verdict


def noise_block(root: Path) -> dict:
    """Stats for the two parent replicas. The span is noise, not a harness effect."""
    loaded = {side: _load_named_side(root, side) for side in AA_SIDES}
    left_rows, left_verdict = loaded[AA_SIDES[0]]
    right_rows, right_verdict = loaded[AA_SIDES[1]]
    incompatible = {}
    if left_verdict is not None:
        incompatible[AA_SIDES[0]] = left_verdict
    if right_verdict is not None:
        incompatible[AA_SIDES[1]] = right_verdict
    left_scores = task_score_means(left_rows)
    right_scores = task_score_means(right_rows)
    score_spans = {
        task: abs(right_scores[task] - left_scores[task])
        for task in set(left_scores) & set(right_scores)
    }
    spans = []
    for row in task_metric_deltas(left_rows, right_rows):
        metrics = {}
        for key, metric in row["metrics"].items():
            delta = metric["delta"]
            metrics[key] = {
                "span": None if delta is None else abs(delta),
                "delta": delta,
                "ci": metric["ci"],
                "digits": metric["digits"],
            }
        spans.append({
            "task": row["task"],
            "metrics": metrics,
            "score_span": score_spans.get(row["task"]),
        })
    named = {row["task"] for row in spans}
    for task in sorted(set(score_spans) - named):
        spans.append({
            "task": task,
            "metrics": {
                key: {"span": None, "delta": None, "ci": None, "digits": digits}
                for key, _label, _value_of, digits in TASK_DELTAS
            },
            "score_span": score_spans[task],
        })
    spans.sort(key=lambda row: row["task"])
    score_deltas = paired_deltas(left_rows, right_rows)
    arm_path = root / "arm.json"
    arm = {}
    if arm_path.is_file():
        try:
            parsed = json.loads(arm_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            arm = parsed
    return {
        "arm": "parent-vs-parent",
        "sha": arm.get("sha") or "",
        "sides": {
            AA_SIDES[0]: side_stats(left_rows),
            AA_SIDES[1]: side_stats(right_rows),
        },
        "incompatible": incompatible,
        "task_spans": spans,
        "score_span": None if not score_deltas else _mean([abs(item) for item in score_deltas]),
        "paired_tasks": len(score_deltas),
    }


def pr_record(pr: PullRequest, out_dir: Path) -> dict:
    root = out_dir / pr.pr
    incompatible = {}
    for side in (Side.WITHOUT, Side.WITH):
        for kind in ("incompatible", "infra"):
            path = root / f"{side.value}.{kind}.json"
            if path.is_file():
                incompatible[side.value] = json.loads(path.read_text(encoding="utf-8"))
                break
    without_rows = [] if "without" in incompatible else load_jsonl(root / "without.jsonl")
    with_rows = [] if "with" in incompatible else load_jsonl(root / "with.jsonl")
    left_tool = _load_toolchain(root, "without", without_rows)
    right_tool = _load_toolchain(root, "with", with_rows)
    left = side_stats(without_rows)
    right = side_stats(with_rows)
    deltas = paired_deltas(without_rows, with_rows)
    point = _mean(deltas)
    interval = bootstrap_ci(deltas)
    has_ab = any(_side_files(root, side.value) for side in (Side.WITHOUT, Side.WITH))
    has_aa = any(_side_files(root, side) for side in AA_SIDES)
    record = {
        "pr": pr.pr,
        "repo": pr.repo,
        "title": pr.title,
        "category": pr.category,
        "harness_change": pr.harness_change,
        "incompatible": incompatible,
        "toolchain": {"without": left_tool, "with": right_tool},
        "sdk_changed": sdk_versions_differ(left_tool, right_tool),
        "without": left,
        "with": right,
        "delta_score": point,
        "delta_ci": interval,
        "paired_tasks": len(deltas),
        "task_deltas": task_metric_deltas(without_rows, with_rows),
        "headroom": headroom_report(without_rows, with_rows),
        "comparison": "ab",
    }
    if has_aa and not has_ab:
        record["comparison"] = "parent-vs-parent"
        record["noise"] = noise_block(root)
        record["delta_score"] = None
        record["delta_ci"] = None
        record["paired_tasks"] = 0
        record["task_deltas"] = []
        record["headroom"] = {"tasks": [], "delta_pass_rate": None, "delta_ci": None, "n": 0}
        record["incompatible"] = {}
    elif has_aa:
        record["noise"] = noise_block(root)
    return record


def _toolchain_line(side: str, tool: dict) -> str:
    parts = []
    if tool.get("bun"):
        parts.append(f"bun {tool['bun']}")
    if tool.get("ai"):
        parts.append(f"ai {tool['ai']}")
    if tool.get("anthropic"):
        parts.append(f"@ai-sdk/anthropic {tool['anthropic']}")
    if not parts:
        return ""
    return f"{side} toolchain: " + ", ".join(parts)


def _side_cells(stats: dict) -> list[str]:
    return [
        _fmt(stats["pass_rate"]),
        _fmt(stats["mean_score"]),
        _fmt(stats["median_time_s"]),
        _fmt(stats["mean_tokens"], 1),
    ]


def render_parent_noise(records: list[dict]) -> str:
    """Render parent replicas. Side names stay aa-1 and aa-2."""
    lines = [
        "# Parent-vs-parent noise",
        "",
        "Both sides ran the parent build. aa-1 and aa-2 are replicas.",
        "The span is the noise range for that task. It is not a harness comparison.",
        "",
        "| PR | Parent SHA | aa-1 pass rate | aa-2 pass rate | Score span | Paired tasks |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in records:
        noise = item.get("noise") or {}
        sides = noise.get("sides") or {}
        left = sides.get(AA_SIDES[0]) or {}
        right = sides.get(AA_SIDES[1]) or {}
        lines.append(
            f"| {item['pr']} | {noise.get('sha') or ''} | {_fmt(left.get('pass_rate'))} | "
            f"{_fmt(right.get('pass_rate'))} | {_fmt(noise.get('score_span'))} | "
            f"{noise.get('paired_tasks') or 0} |"
        )
    lines.append("")
    for item in records:
        noise = item.get("noise") or {}
        sides = noise.get("sides") or {}
        lines.append(f"## PR {item['pr']}")
        lines.append("")
        lines.append("Arm: parent-vs-parent")
        if noise.get("sha"):
            lines.append(f"Parent SHA: {noise['sha']}")
        lines.append("")
        if noise.get("incompatible"):
            for side, body in noise["incompatible"].items():
                status = body.get("status") or "incompatible"
                lines.append(f"{side} is {status}: {body.get('reason', '')}")
            lines.append("")
        lines.append("| Side | Pass rate | Mean score | Median seconds | Mean tokens |")
        lines.append("| --- | --- | --- | --- | --- |")
        for side in AA_SIDES:
            stats = sides.get(side) or {
                "pass_rate": None, "mean_score": None, "median_time_s": None, "mean_tokens": None,
            }
            lines.append(f"| {side} | " + " | ".join(_side_cells(stats)) + " |")
        lines.append("")
        lines.append(
            f"Score span (absolute difference of task means): {_fmt(noise.get('score_span'))} "
            f"on {noise.get('paired_tasks') or 0} paired tasks."
        )
        lines.append("")
        lines.extend(_noise_task_lines(noise.get("task_spans") or []))
        lines.append("")
    return "\n".join(lines)


def _noise_task_lines(rows: list[dict]) -> list[str]:
    lines = ["### Per-task noise range", ""]
    if not rows:
        lines.append("No paired task has time, turns, tokens, or cost on both replicas.")
        return lines
    headers = ["Task", "Score span"]
    for _key, label, _value_of, _digits in TASK_DELTAS:
        headers.append(f"{label} span")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        cells = [row["task"], _fmt(row.get("score_span"))]
        for key, _label, _value_of, _digits in TASK_DELTAS:
            metric = row["metrics"][key]
            cells.append(_fmt(metric["span"], metric["digits"]))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_markdown(records: list[dict]) -> str:
    noise_only = [item for item in records if item.get("comparison") == "parent-vs-parent"]
    ab_records = [item for item in records if item.get("comparison") != "parent-vs-parent"]
    if not noise_only and not any(item.get("noise") for item in ab_records):
        return _render_ab_markdown(records)
    if not ab_records:
        return render_parent_noise(noise_only)
    text = _render_ab_markdown(ab_records)
    attached = [item for item in ab_records if item.get("noise")]
    if noise_only or attached:
        text = text.rstrip() + "\n\n" + render_parent_noise(noise_only + attached)
    return text


def _render_ab_markdown(records: list[dict]) -> str:
    ranked = sorted(
        records,
        key=lambda item: (item["delta_score"] is None, -(item["delta_score"] or 0)),
    )
    heading = "# Harness A/B" if any(item.get("repo") for item in records) else "# OpenCode harness A/B"
    lines = [heading, "", "## Ranked by mean per-task score delta", ""]
    lines.append("| PR | Category | Delta score | 95% CI | Paired tasks |")
    lines.append("| --- | --- | --- | --- | --- |")
    for item in ranked:
        ci_text = _ci_text(item["delta_ci"])
        reason = ""
        if item["incompatible"]:
            reason = "; ".join(
                f"{side}: {body.get('reason', '')}" for side, body in item["incompatible"].items()
            )
        if item.get("sdk_changed"):
            reason = " ".join(part for part in (reason, SDK_CHANGED) if part)
        delta = reason or _fmt(item["delta_score"])
        lines.append(
            f"| {item['pr']} | {item['category']} | {delta} | {ci_text} | {item['paired_tasks']} |"
        )
    lines.append("")
    lines.append("Pass rate drops rows whose failure class is infra, rate_limited, or stalled.")
    lines.append("The score delta is the unweighted mean of per-task (with minus without) score means.")
    lines.append("The interval resamples those tasks 1000 times with seed 0.")
    lines.append(
        "Per-task time, turns, tokens, and cost deltas are with-side means minus without-side means."
    )
    lines.append("Each of those intervals resamples that task's trials 1000 times with seed 0.")
    lines.append(
        "Headroom tasks have a mean score below 1.0 on either side. "
        "The pass-rate delta there uses only those tasks and the same task bootstrap."
    )
    lines.append("")
    for item in ranked:
        lines.append(f"## PR {item['pr']}")
        lines.append("")
        if item.get("repo"):
            lines.append(f"Repo: {item['repo']}")
        lines.append(f"Title: {item['title']}")
        lines.append(f"Category: {item['category']}")
        lines.append(f"Harness change: {item['harness_change']}")
        lines.append("")
        for side in ("without", "with"):
            text = _toolchain_line(side, item.get("toolchain", {}).get(side) or {})
            if text:
                lines.append(text)
        if item.get("sdk_changed"):
            lines.append(SDK_CHANGED)
        if item.get("toolchain") and any(item["toolchain"].values()):
            lines.append("")
        if item["incompatible"]:
            for side, body in item["incompatible"].items():
                status = body.get("status") or "incompatible"
                lines.append(f"{side} is {status}: {body.get('reason', '')}")
            lines.append("")
        lines.append("| Side | Pass rate | Mean score | Median seconds | Mean tokens |")
        lines.append("| --- | --- | --- | --- | --- |")
        lines.append("| without | " + " | ".join(_side_cells(item["without"])) + " |")
        lines.append("| with | " + " | ".join(_side_cells(item["with"])) + " |")
        ci_text = _ci_text(item["delta_ci"]) or "n/a"
        lines.append("")
        lines.append(
            f"Score delta (with minus without): {_fmt(item['delta_score'])} "
            f"on {item['paired_tasks']} paired tasks. 95% bootstrap interval: {ci_text}."
        )
        lines.append("")
        lines.extend(_task_delta_lines(item["task_deltas"]))
        lines.append("")
        lines.extend(_headroom_lines(item["headroom"]))
        lines.append("")
    return "\n".join(lines)


def _task_delta_lines(rows: list[dict]) -> list[str]:
    lines = ["### Per-task deltas", ""]
    if not rows:
        lines.append("No paired task has time, turns, tokens, or cost on both sides.")
        return lines
    headers = ["Task"]
    for _key, label, _value_of, _digits in TASK_DELTAS:
        headers.extend([label, "95% CI"])
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        cells = [row["task"]]
        for key, _label, _value_of, _digits in TASK_DELTAS:
            metric = row["metrics"][key]
            cells.append(_fmt(metric["delta"], metric["digits"]))
            cells.append(_ci_text(metric["ci"], metric["digits"]))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _headroom_lines(headroom: dict) -> list[str]:
    lines = ["### Headroom", ""]
    tasks = headroom["tasks"]
    if not tasks:
        lines.append("No paired task has a mean score below 1.0 on either side.")
        return lines
    lines.append("| Task | Without score | With score | Without pass rate | With pass rate |")
    lines.append("| --- | --- | --- | --- | --- |")
    for task in tasks:
        lines.append(
            "| "
            + " | ".join([
                task["task"],
                _fmt(task["without_score"]),
                _fmt(task["with_score"]),
                _fmt(task["without_pass_rate"]),
                _fmt(task["with_pass_rate"]),
            ])
            + " |"
        )
    lines.append("")
    ci_text = _ci_text(headroom["delta_ci"]) or "n/a"
    lines.append(
        f"Pass-rate delta on headroom tasks (with minus without): "
        f"{_fmt(headroom['delta_pass_rate'])} on {headroom['n']} {_task_word(headroom['n'])}. "
        f"95% bootstrap interval: {ci_text}."
    )
    return lines


def render_csv(records: list[dict]) -> str:
    import io
    buf = io.StringIO()
    fields = [
        "pr", "repo", "title", "category", "harness_change",
        "without_pass_rate", "with_pass_rate",
        "without_mean_score", "with_mean_score", "delta_score",
        "delta_ci_low", "delta_ci_high", "paired_tasks",
        "without_median_time_s", "with_median_time_s",
        "without_mean_tokens", "with_mean_tokens",
        "headroom_tasks", "headroom_n", "headroom_pass_delta",
        "headroom_pass_ci_low", "headroom_pass_ci_high",
        "incompatible",
        "without_bun", "without_ai", "without_anthropic",
        "with_bun", "with_ai",         "with_anthropic",
        "sdk_changed",
        "comparison",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for item in records:
        ci = item["delta_ci"] or (None, None)
        headroom = item["headroom"]
        head_ci = headroom["delta_ci"] or (None, None)
        writer.writerow({
            "pr": item["pr"],
            "repo": item.get("repo") or "",
            "title": item["title"],
            "category": item["category"],
            "harness_change": item["harness_change"],
            "without_pass_rate": _fmt(item["without"]["pass_rate"]),
            "with_pass_rate": _fmt(item["with"]["pass_rate"]),
            "without_mean_score": _fmt(item["without"]["mean_score"]),
            "with_mean_score": _fmt(item["with"]["mean_score"]),
            "delta_score": _fmt(item["delta_score"]),
            "delta_ci_low": _fmt(ci[0]),
            "delta_ci_high": _fmt(ci[1]),
            "paired_tasks": item["paired_tasks"],
            "without_median_time_s": _fmt(item["without"]["median_time_s"]),
            "with_median_time_s": _fmt(item["with"]["median_time_s"]),
            "without_mean_tokens": _fmt(item["without"]["mean_tokens"], 1),
            "with_mean_tokens": _fmt(item["with"]["mean_tokens"], 1),
            "headroom_tasks": ";".join(task["task"] for task in headroom["tasks"]),
            "headroom_n": headroom["n"],
            "headroom_pass_delta": _fmt(headroom["delta_pass_rate"]),
            "headroom_pass_ci_low": _fmt(head_ci[0]),
            "headroom_pass_ci_high": _fmt(head_ci[1]),
            "incompatible": json.dumps(item["incompatible"]),
            "without_bun": (item.get("toolchain") or {}).get("without", {}).get("bun", ""),
            "without_ai": (item.get("toolchain") or {}).get("without", {}).get("ai", ""),
            "without_anthropic": (item.get("toolchain") or {}).get("without", {}).get("anthropic", ""),
            "with_bun": (item.get("toolchain") or {}).get("with", {}).get("bun", ""),
            "with_ai": (item.get("toolchain") or {}).get("with", {}).get("ai", ""),
            "with_anthropic": (item.get("toolchain") or {}).get("with", {}).get("anthropic", ""),
            "sdk_changed": "yes" if item.get("sdk_changed") else "",
            "comparison": item.get("comparison") or "ab",
        })
    return buf.getvalue()


def write_report(out_dir: Path, prs: tuple[PullRequest, ...], md_path: Path, csv_path: Path) -> None:
    records = [pr_record(pr, out_dir) for pr in prs]
    md_path.write_text(render_markdown(records), encoding="utf-8")
    csv_path.write_text(render_csv(records), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize OpenCode A/B results")
    parser.add_argument("prs", type=Path, help="PR list CSV or JSONL")
    parser.add_argument("--results", type=Path, default=Path("results/ab"))
    parser.add_argument("--out", type=Path, default=None, help="directory for summary.md and summary.csv")
    args = parser.parse_args(argv)
    out = args.out or args.results
    out.mkdir(parents=True, exist_ok=True)
    try:
        prs = parse_prs(args.prs)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        return 2
    write_report(args.results, prs, out / "summary.md", out / "summary.csv")
    print(out / "summary.md")
    print(out / "summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
