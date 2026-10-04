"""Per-PR pass rate, score, time, and tokens, plus a ranked delta table."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from pathlib import Path

from thesis.ab.prs import PullRequest, Side, parse_prs

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


def row_cost(row: dict) -> float | None:
    """USD from the four token fields. None when any field is missing."""
    total = 0.0
    for field, rate in RATES.items():
        value = row.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        total += (float(value) / 1_000_000.0) * rate
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
        if all(isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool) for field in TOKEN_FIELDS):
            tokens.append(sum(float(row[field]) for field in TOKEN_FIELDS))
    n = len(kept)
    return {
        "n": n,
        "pass_rate": (len(passed) / n) if n else None,
        "mean_score": _mean(scores),
        "median_time_s": _median(times),
        "mean_tokens": _mean(tokens),
    }


def task_score_means(rows: list[dict]) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        if not countable(row):
            continue
        if not isinstance(row.get("score"), (int, float)) or isinstance(row.get("score"), bool):
            continue
        buckets.setdefault(str(row.get("task")), []).append(float(row["score"]))
    return {task: sum(values) / len(values) for task, values in buckets.items() if values}


def paired_deltas(without_rows: list[dict], with_rows: list[dict]) -> list[float]:
    left = task_score_means(without_rows)
    right = task_score_means(with_rows)
    return [right[task] - left[task] for task in sorted(set(left) & set(right))]


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
    lo = means[int(0.025 * (draws - 1))]
    hi = means[min(draws - 1, int(round(0.975 * (draws - 1))))]
    return (lo, hi)


def _fmt(value, digits=3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def pr_record(pr: PullRequest, out_dir: Path) -> dict:
    root = out_dir / pr.pr
    incompatible = {}
    for side in (Side.WITHOUT, Side.WITH):
        path = root / f"{side.value}.incompatible.json"
        if path.is_file():
            incompatible[side.value] = json.loads(path.read_text(encoding="utf-8"))
    without_rows = load_jsonl(root / "without.jsonl")
    with_rows = load_jsonl(root / "with.jsonl")
    left = side_stats(without_rows)
    right = side_stats(with_rows)
    deltas = paired_deltas(without_rows, with_rows)
    point = _mean(deltas)
    interval = bootstrap_ci(deltas)
    return {
        "pr": pr.pr,
        "title": pr.title,
        "category": pr.category,
        "harness_change": pr.harness_change,
        "incompatible": incompatible,
        "without": left,
        "with": right,
        "delta_score": point,
        "delta_ci": interval,
        "paired_tasks": len(deltas),
    }


def _side_cells(stats: dict) -> list[str]:
    return [
        _fmt(stats["pass_rate"]),
        _fmt(stats["mean_score"]),
        _fmt(stats["median_time_s"]),
        _fmt(stats["mean_tokens"], 1),
    ]


def render_markdown(records: list[dict]) -> str:
    ranked = sorted(
        records,
        key=lambda item: (item["delta_score"] is None, -(item["delta_score"] or 0)),
    )
    lines = ["# OpenCode harness A/B", "", "## Ranked by mean per-task score delta", ""]
    lines.append("| PR | Category | Delta score | 95% CI | Paired tasks |")
    lines.append("| --- | --- | --- | --- | --- |")
    for item in ranked:
        ci = item["delta_ci"]
        ci_text = "" if ci is None else f"{ci[0]:.3f} to {ci[1]:.3f}"
        reason = ""
        if item["incompatible"]:
            reason = "; ".join(
                f"{side}: {body.get('reason', '')}" for side, body in item["incompatible"].items()
            )
        delta = reason or _fmt(item["delta_score"])
        lines.append(
            f"| {item['pr']} | {item['category']} | {delta} | {ci_text} | {item['paired_tasks']} |"
        )
    lines.append("")
    lines.append("Pass rate drops rows whose failure class is infra, rate_limited, or stalled.")
    lines.append("The score delta is the unweighted mean of per-task (with minus without) score means.")
    lines.append("The interval resamples those tasks 1000 times with seed 0.")
    lines.append("")
    for item in ranked:
        lines.append(f"## PR {item['pr']}")
        lines.append("")
        lines.append(f"Title: {item['title']}")
        lines.append(f"Category: {item['category']}")
        lines.append(f"Harness change: {item['harness_change']}")
        lines.append("")
        if item["incompatible"]:
            for side, body in item["incompatible"].items():
                lines.append(f"{side} is incompatible: {body.get('reason', '')}")
            lines.append("")
        lines.append("| Side | Pass rate | Mean score | Median seconds | Mean tokens |")
        lines.append("| --- | --- | --- | --- | --- |")
        lines.append("| without | " + " | ".join(_side_cells(item["without"])) + " |")
        lines.append("| with | " + " | ".join(_side_cells(item["with"])) + " |")
        ci = item["delta_ci"]
        ci_text = "n/a" if ci is None else f"{ci[0]:.3f} to {ci[1]:.3f}"
        lines.append("")
        lines.append(
            f"Score delta (with minus without): {_fmt(item['delta_score'])} "
            f"on {item['paired_tasks']} paired tasks. 95% bootstrap interval: {ci_text}."
        )
        lines.append("")
    return "\n".join(lines)


def render_csv(records: list[dict]) -> str:
    import io
    buf = io.StringIO()
    fields = [
        "pr", "title", "category", "harness_change",
        "without_pass_rate", "with_pass_rate",
        "without_mean_score", "with_mean_score", "delta_score",
        "delta_ci_low", "delta_ci_high", "paired_tasks",
        "without_median_time_s", "with_median_time_s",
        "without_mean_tokens", "with_mean_tokens",
        "incompatible",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for item in records:
        ci = item["delta_ci"] or (None, None)
        writer.writerow({
            "pr": item["pr"],
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
            "incompatible": json.dumps(item["incompatible"]),
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
