"""Ideation agent: 5 prompt / tool-metadata alternatives per failure, each run at N=30 (SEA-110).

Inputs: a failed trial of a runner run, its trace, and the credit-assignment
rows for it (Method A ``credit_a.jsonl`` and/or Method B
``credit_b.jsonl``). The ideator model proposes **exactly**
``N_ALTERNATIVES`` alternatives. Each is a patch (``patches.py``) confined to
the system prompt and tool-call metadata.
- Every proposal is validated. Out-of-surface proposals are stored as
  ``rejected`` with reasons and never run.
- If the ideator returns the wrong number, or any invalid proposal, it is
  re-asked once with the reasons.

Every proposal row records its parent trial and the credit method (``A``,
``B`` or ``A+B``) with the credit rows it came from.

The drawn-failure driver (``propose_drawn``) asks the ideator **once** per
picked failure. That one input contains Method A and Method B evidence
together. Each alternative cites the evidence it uses (``A``, ``B``, or
``both``, with the evidence id). An alternative with no citation is stored
``rejected`` and ``uncited``, and is not run. When Method B's status is
``empty_window`` (the failure is at step 1), that one input contains only
Method A's evidence, and the row records that.

Evaluation: each accepted proposal runs ``n_trials`` (default 30) on the
parent's task and model through the SEA-107 runner, with the patch applied
by the recording proxy. ``decide`` compares it with the fresh baseline
(``credit_baseline.json``, same task and model, N). The pilot ``summary.jsonl``
row is not a baseline and there is no fallback. Two stages (``evaluate``;
João Sedoc via Sean, SEA-110, 2026-11-13):
- **Selection:** a *candidate* iff both sides completed all N trials and
  the alternative has more passes than the fresh baseline (``decide``: a bare
  beat, no significance gate; 1/30 vs 0/30 qualifies; a tie does not).
- **Confirmation:** each candidate gets a fresh N-trial alternative run and a
  new fresh N-trial baseline run (new trial ids, no reuse of the selection
  trials or of the selection baseline). ``success`` iff it beats that new
  baseline again. ``confirm`` is ``all`` (default: every selection candidate)
  or ``top`` (the top ``confirm_k`` candidates per cell, default 1, across
  that cell's drawn failures).

Both stages record the one-sided Fisher exact p as a reported statistic only.
``evaluate`` does not take ``alpha`` and always uses ``ALPHA`` (1.0) on a
scored row. It refuses to write a scored row whose alpha is not 1.0. A cap
stop is not scored: ``decide`` is not called, and the row is
``stopped_by_cap`` with ``alpha`` null. ``decide(alpha=...)`` remains for a
library check. A p-gated view is a report column computed from the recorded
Fisher p and does not change ``candidate``, ``confirmed``, or ``success``.
Each arm reuses the fresh baseline's recorded image, with smoke compaction
off. Every arm row records ``code_commit``. ``evaluate`` refuses an arm whose
``code_commit`` differs from the fresh baseline's ``baseline_commit``.
``spend_cap_usd`` is the per-cell cap (``--max-usd-per-cell``). ``max_usd``
is the invocation total. ``runner.ideation_estimate`` prices selection plus
confirmation.

Tables (in the run directory, separate from the trial and credit tables):
``ideation.jsonl`` (proposals) and ``ideation_results.jsonl`` (one row per
evaluated proposal).
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from obench.reflection import runner as rn
from obench.reflection.credit_baseline import BaselineError, _check_fresh_image, fresh_baseline_row
from obench.reflection.credit_draw import drawn_picks
from obench.reflection.credit_locator import MAX_SET_ASIDE, check_max_set_aside, read_trace
from obench.reflection.patches import OPS, PATCH_SCHEMA, patch_id, validate_patch

N_ALTERNATIVES = 5
ALPHA = 1.0   # no significance gate (Sean, 2026-11-13); fisher_p is still reported
PROMPT_VERSION = "I1"
COMBINED_PROMPT_VERSION = "I2"  # one input per drawn failure; each alternative cites A, B, or both
PROPOSAL_SCHEMA = "openbench.reflection.ideation/v1"
RESULT_SCHEMA = "openbench.reflection.ideation_result/v1"
CREDIT_METHODS = ("A", "B", "A+B")
IDEATOR_MODEL = "claude-opus-5-5"              # open: configurable; not the model under test by design
IDEATOR_THINKING = {"type": "adaptive"}        # set explicitly on every ideator request
CONFIRM_ALL = "all"                            # every selection candidate is confirmed
CONFIRM_TOP = "top"                            # top confirm_k candidates per cell (model, task)
CONFIRM_MODES = (CONFIRM_ALL, CONFIRM_TOP)
CONFIRM_SKIPPED_NOT_TOP = "not_top"            # a candidate outside the top confirm_k
DEFAULT_CONFIRM_K = 1


def check_confirm(value: str) -> str:
    """``all`` (default) or ``top``. Anything else is an error."""
    if value not in CONFIRM_MODES:
        raise ValueError(f"confirm must be 'top' or 'all', got {value!r}")
    return value


def check_confirm_k(value, confirm: str | None = None) -> int:
    """``confirm_k`` is an int >= 1. A value other than 1 is only valid for ``top``."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"confirm_k must be an int >= 1, got {value!r}")
    if confirm is not None and confirm != CONFIRM_TOP and value != 1:
        raise ValueError(f"confirm_k must be 1 when confirm is {confirm!r}; got {value}")
    return value


@dataclass(frozen=True)
class IdeationConfig:
    """Evaluation settings. ``confirm_k`` selects how many ``top`` candidates to confirm."""
    confirm: str = CONFIRM_ALL
    confirm_k: int = DEFAULT_CONFIRM_K

    @classmethod
    def from_dict(cls, raw: dict) -> "IdeationConfig":
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown ideation config keys: {sorted(unknown)}")
        cfg = cls(**raw)
        check_confirm(cfg.confirm)
        check_confirm_k(cfg.confirm_k, cfg.confirm)
        return cfg


def resolve_config(config_path: Path | None = None, confirm: str | None = None,
                   confirm_k: int | None = None) -> IdeationConfig:
    """Settings from ``--config``. ``--confirm`` and ``--confirm-k`` override the file."""
    cfg = IdeationConfig.from_dict(json.loads(Path(config_path).read_text(encoding="utf-8"))) if config_path else IdeationConfig()
    if confirm is None and confirm_k is None:
        return cfg
    data = asdict(cfg)
    if confirm is not None:
        data["confirm"] = confirm
    if confirm_k is not None:
        data["confirm_k"] = confirm_k
    return IdeationConfig.from_dict(data)


class Ideator(Protocol):
    model_id: str

    def propose(self, prompt: str) -> tuple[str, dict | None]:
        """Raw JSON text of the proposals, and usage."""


def _digest(steps: list[dict], limit: int = 1200) -> list[dict]:
    out = []
    for s in steps:
        calls = [{"tool": c.get("name"), "arguments": c.get("arguments"),
                  "result": str(c.get("result"))[:limit], "status": c.get("status")} for c in s.get("tool_calls") or []]
        out.append({"step": s.get("step"), "text": (s.get("assistant_text") or "")[:limit], "tool_calls": calls})
    return out


def build_prompt(trial: dict, steps: list[dict], credit: dict) -> str:
    """Prompt for one failure. Deterministic for the same inputs.

    A credit payload with an ``evidence`` list is ``COMBINED_PROMPT_VERSION``:
    Method A and Method B in one input, and each alternative must cite the
    items it uses. Any other payload is ``PROMPT_VERSION``.
    """
    tools = sorted({c.get("name") for s in steps for c in s.get("tool_calls") or [] if c.get("name")})
    spec = {op: sorted(fields) for op, fields in OPS.items()}
    cite = ""
    answer = '{"alternatives": [{"rationale": <why>, "patch": <patch>}, ...]}'
    if isinstance(credit, dict) and credit.get("evidence"):
        only_a = credit.get("method_b_status") == "empty_window" or credit.get("ideator_evidence") == ["A"]
        cite = (
            "Each alternative must cite the evidence it uses. citations is a non-empty list of "
            "{\"method\": \"A\" | \"B\" | \"both\", \"evidence\": <id or [ids]>} using ids from the evidence list. "
            "method A or B names one id of that method. method both names one A id and one B id. "
            + ("Method B returned empty_window (the failure is at step 1, so there is no prior step). "
               "Cite Method A only.\n" if only_a else "Cite A, B, or both.\n")
        )
        answer = ('{"alternatives": [{"rationale": <why>, "patch": <patch>, '
                  '"citations": [{"method": "A" | "B" | "both", "evidence": <id or [ids]>}]}, ...]}')
    return (
        "A coding agent failed a task. Credit assignment located where it went wrong (below). Propose exactly "
        f"{N_ALTERNATIVES} alternative changes that might make the agent succeed. You may ONLY change the agent's "
        "system prompt or its tools' descriptions / parameter descriptions. No code changes, no task or checker "
        "changes, no model or sampling changes.\n"
        f"Each alternative is a patch: {{\"schema\": \"{PATCH_SCHEMA}\", \"ops\": [...]}} with ops from {json.dumps(spec)}. "
        f"Tools seen in this trace: {tools}.\n"
        f"{cite}"
        f"Answer with JSON only: {answer}.\n\n"
        + json.dumps({"task": trial["task"], "model": trial["model"], "credit": credit, "trace": _digest(steps)},
                     sort_keys=True, indent=1))


def _credit_row(run_dir: Path, trial_id: str, table: str, method: str) -> dict:
    rows = [r for r in rn.read_rows(run_dir / table) if r["trial_id"] == trial_id]
    if not rows:
        raise ValueError(f"no Method {method} row for trial {trial_id} in {table}")
    return rows[0]


def _credit_for(run_dir: Path, trial_id: str, method: str) -> dict:
    out = {}
    for m, table in (("A", "credit_a.jsonl"), ("B", "credit_b.jsonl")):
        if m not in method:
            continue
        r = _credit_row(run_dir, trial_id, table, m)
        out[m] = ({"failing_step": r["failing_step"], "signal": r["signal"], "rationale": r["rationale"],
                   "evidence": r["evidence"], "rule_version": r["rule_version"]} if m == "A" else
                  {"first_failing_step": r["first_failing_step"], "weights": r["weights"], "labels": r["labels"],
                   "prompt_version": r["prompt_version"], "system1_model": r["system1_model"]})
    return out


def _b_status(row: dict) -> str:
    """Method B status, including a row written before ``status`` existed."""
    if row.get("status"):
        return row["status"]
    if row.get("judge_error") == "empty_trace" or row.get("first_failing_step") is None:
        return "empty_trace"
    if row.get("judge_error"):
        return "judge_error"
    if not row.get("window"):
        return "empty_window"
    return "ok"


def evidence_catalog(run_dir: Path, trial: dict) -> tuple[list[dict], dict]:
    """Evidence items for one combined ideator input, plus the fields stored on each proposal.

    Method B ``empty_window`` (no step before the failure) contributes no item.
    The metadata still records that status and that the ideator saw only A.
    """
    trial_id = trial["trial_id"]
    method_a = _credit_row(run_dir, trial_id, "credit_a.jsonl", "A")
    method_b = _credit_row(run_dir, trial_id, "credit_b.jsonl", "B")
    status = _b_status(method_b)
    window = list(method_b.get("window") or [])
    length = method_b.get("window_length", len(window))
    a_step = method_a.get("failing_step")
    items = [{
        "id": "A:failing_step", "method": "A",
        "pointer": method_a.get("trace_step") or f"credit_a.jsonl#{trial_id}#step={a_step}",
        "failing_step": a_step, "signal": method_a.get("signal"),
        "rationale": method_a.get("rationale"), "evidence": method_a.get("evidence"),
        "rule_version": method_a.get("rule_version"),
    }]
    shown = ["A"]
    if status == "ok" and window:
        labels = method_b.get("labels") or {}
        items.append({
            "id": "B:window", "method": "B",
            "pointer": f"credit_b.jsonl#{trial_id}#window={window}",
            "window": window, "window_length": length, "k": method_b.get("k"),
            "labels": labels, "first_failing_step": method_b.get("first_failing_step"),
            "prompt_version": method_b.get("prompt_version"),
        })
        for step in window:
            items.append({
                "id": f"B:step:{step}", "method": "B",
                "pointer": f"credit_b.jsonl#{trial_id}#step={step}",
                "step": step, "label": labels.get(str(step)),
            })
        shown = ["A", "B"]
    meta = {
        "ideator_evidence": shown, "method_b_status": status, "method_b_window_length": length,
        "credit_rows": {"A": f"credit_a.jsonl#{trial_id}", "B": f"credit_b.jsonl#{trial_id}"},
    }
    return items, meta


def _evidence_ids(evidence) -> list[str] | None:
    if isinstance(evidence, str) and evidence:
        return [evidence]
    if isinstance(evidence, list) and evidence and all(isinstance(item, str) and item for item in evidence):
        return list(evidence)
    return None


def citation_problems(alt, catalog: dict[str, dict]) -> list[str]:
    """Reasons an alternative's citations are missing or do not point at the evidence it was shown."""
    if not isinstance(alt, dict):
        return ["no citation"]
    raw = alt.get("citations")
    if not isinstance(raw, list) or not raw:
        return ["no citation"]
    problems = []
    for i, cite in enumerate(raw):
        if not isinstance(cite, dict):
            problems.append(f"citation {i}: not an object")
            continue
        method = cite.get("method")
        if method not in ("A", "B", "both"):
            problems.append(f"citation {i}: method must be A, B, or both")
            continue
        ids = _evidence_ids(cite.get("evidence"))
        if ids is None:
            problems.append(f"citation {i}: missing evidence id")
            continue
        unknown = [eid for eid in ids if eid not in catalog]
        if unknown:
            problems.append(f"citation {i}: unknown evidence {unknown[0]}")
            continue
        methods = {catalog[eid]["method"] for eid in ids}
        if method == "both":
            if "A" not in methods or "B" not in methods:
                problems.append(f"citation {i}: both must name an A item and a B item")
        elif methods != {method} or len(ids) != 1:
            problems.append(f"citation {i}: {method} must name one {method} evidence item")
    return problems


def citation_rows(alt, catalog: dict[str, dict]) -> list[dict]:
    """Citations that point at known evidence, with the pointer stored on the row."""
    if not isinstance(alt, dict) or not isinstance(alt.get("citations"), list):
        return []
    out = []
    for cite in alt["citations"]:
        if not isinstance(cite, dict) or cite.get("method") not in ("A", "B", "both"):
            continue
        ids = _evidence_ids(cite.get("evidence"))
        if ids is None or any(eid not in catalog for eid in ids):
            continue
        pointers = [catalog[eid]["pointer"] for eid in ids]
        out.append({
            "method": cite["method"],
            "evidence": ids[0] if cite["method"] != "both" and len(ids) == 1 else ids,
            "pointer": pointers[0] if len(pointers) == 1 else pointers,
        })
    return out


def drawn_trials(run_dir: Path) -> list[dict]:
    """Drawn failures in ``(cell, draw_order)``. ``EXCLUDED``, ``NOT_LISTED``, and ``NO_ROWS`` are skipped."""
    run_dir = Path(run_dir)
    by_id = {row["trial_id"]: row for row in rn.read_rows(run_dir / "trials.jsonl")}
    picked = []
    for pick in drawn_picks(run_dir):
        trial = by_id.get(pick["trial_id"])
        if trial is None:
            raise ValueError(f"{pick['cell']}: drawn trial {pick['trial_id']} is not in trials.jsonl")
        picked.append(trial)
    return picked


def parse_alternatives(raw: str) -> list[dict]:
    doc = json.loads(raw)
    alts = doc.get("alternatives")
    if not isinstance(alts, list):
        raise ValueError("no 'alternatives' list")
    return alts


def propose(run_dir: Path, trial: dict, method: str, ideator: Ideator, max_asks: int = 2) -> list[dict]:
    """Proposal rows for one failed trial (appended to ``ideation.jsonl``).

    ``A+B`` is one ideator input. Each alternative must cite the evidence it
    uses. An alternative with no citation is ``rejected`` and ``uncited``.
    """
    if method not in CREDIT_METHODS:
        raise ValueError(f"credit method must be one of {CREDIT_METHODS}")
    run_dir = Path(run_dir)
    steps = read_trace(run_dir / trial["trace"]) if trial.get("trace") else []
    catalog = None
    meta: dict = {}
    if method == "A+B":
        items, meta = evidence_catalog(run_dir, trial)
        credit = {"evidence": items, "method_b_status": meta["method_b_status"],
                  "ideator_evidence": list(meta["ideator_evidence"])}
        catalog = {item["id"]: item for item in items}
        prompt_version = COMBINED_PROMPT_VERSION
        credit_rows = meta["credit_rows"]
    else:
        credit = _credit_for(run_dir, trial["trial_id"], method)
        prompt_version = PROMPT_VERSION
        credit_rows = {m: f"{'credit_a' if m == 'A' else 'credit_b'}.jsonl#{trial['trial_id']}" for m in credit}
    prompt = build_prompt(trial, steps, credit)
    alts, raw, usage, problems = [], None, None, []
    for _ in range(max_asks):
        ask = prompt if not problems else prompt + "\n\nYour previous answer was rejected: " + "; ".join(problems)
        raw, usage = ideator.propose(ask)
        try:
            alts = parse_alternatives(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            alts, problems = [], [f"unparseable: {exc}"]
            continue
        problems = ([f"expected exactly {N_ALTERNATIVES} alternatives, got {len(alts)}"] if len(alts) != N_ALTERNATIVES else [])
        problems += [f"alternative {i}: {r}" for i, a in enumerate(alts) for r in validate_patch((a or {}).get("patch"))]
        if catalog is not None:
            problems += [f"alternative {i}: {r}" for i, a in enumerate(alts) for r in citation_problems(a, catalog)]
        if not problems:
            break
    rows = []
    for i, alt in enumerate(alts):
        patch = (alt or {}).get("patch") if isinstance(alt, dict) else None
        reasons = validate_patch(patch)
        citations = None
        uncited = False
        if catalog is not None:
            cite_reasons = citation_problems(alt, catalog)
            reasons = reasons + cite_reasons
            citations = citation_rows(alt, catalog)
            uncited = "no citation" in cite_reasons
        row = {
            "schema": PROPOSAL_SCHEMA, "prompt_version": prompt_version, "ideator_model": ideator.model_id,
            "run_id": trial.get("run_id"), "parent_trial_id": trial["trial_id"], "task": trial["task"],
            "model": trial["model"], "credit_method": method, "credit_rows": credit_rows,
            "index": i, "rationale": (alt or {}).get("rationale") if isinstance(alt, dict) else None,
            "patch": patch, "proposal_id": patch_id(patch) if not reasons else None,
            "status": "accepted" if not reasons else "rejected", "rejection_reasons": reasons,
            "complete_set": len(alts) == N_ALTERNATIVES, "raw_ideator_output": raw, "ideator_usage": usage,
        }
        if catalog is not None:
            row.update(citations=citations, uncited=uncited, ideator_evidence=list(meta["ideator_evidence"]),
                       method_b_status=meta["method_b_status"], method_b_window_length=meta["method_b_window_length"])
        rows.append(row)
    with (run_dir / "ideation.jsonl").open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return rows


def propose_drawn(run_dir: Path, ideator: Ideator, max_asks: int = 2) -> list[dict]:
    """One ideation per drawn failure. A and B evidence are one input, not one call per method.

    A re-ask is still that same failure. ``NO_ROWS``, ``EXCLUDED``, and ``NOT_LISTED`` cells are not ideated.
    """
    rows = []
    for trial in drawn_trials(run_dir):
        rows.extend(propose(run_dir, trial, "A+B", ideator, max_asks=max_asks))
    return rows


def fisher_one_sided(alt_pass: int, alt_n: int, base_pass: int, base_n: int) -> float:
    """P(alternative passes >= observed | no difference), hypergeometric."""
    total_pass, total = alt_pass + base_pass, alt_n + base_n
    denom = math.comb(total, alt_n)
    return sum(math.comb(total_pass, k) * math.comb(total - total_pass, alt_n - k)
               for k in range(alt_pass, min(total_pass, alt_n) + 1)) / denom


def summary_row_baseline(*_args, **_kwargs):
    """Retired. Selection used to read the pilot ``summary.jsonl`` row.

    That comparison is gone. ``evaluate`` reads the fresh baseline and raises
    when the cell has none. This function stays so a caller cannot quietly
    grow the old path back.
    """
    raise ValueError("the old summary-row baseline is retired; score against the fresh baseline "
                     "(credit_baseline.json), not summary.jsonl")


def decide(baseline: dict, alternative: dict, n: int = rn.N_TRIALS, alpha: float = ALPHA) -> dict:
    """The success rule. Both sides must have completed all ``n`` trials.

    ``baseline`` is a fresh baseline row (or a confirmation arm's summary),
    never the pilot ``summary.jsonl`` row. ``alpha`` defaults to ``ALPHA``
    (1.0) and does not gate. The Fisher p is still returned.
    """
    complete = baseline.get("completed") == n and alternative.get("completed") == n
    if not complete:
        return {"complete": False, "beats_baseline": False, "fisher_p": None, "success": False,
                "reason": f"needs {n} completed trials on both sides"}
    beats = alternative["passes"] > baseline["passes"]
    p = fisher_one_sided(alternative["passes"], n, baseline["passes"], n)
    success = beats and p <= alpha
    return {"complete": True, "beats_baseline": beats, "fisher_p": round(p, 6), "alpha": alpha,
            "success": success,
            "reason": ("beats baseline at N" if success and alpha >= 1.0 else
                       "beats baseline at N with p <= alpha" if success else
                       "beats baseline but not significant at alpha" if beats else "does not beat baseline")}


def _recorded_image(baseline: dict) -> dict:
    """The fresh baseline's image, passed through so an arm does not re-pin."""
    image = baseline.get("image") if isinstance(baseline.get("image"), dict) else {}
    ref = image.get("ref")
    if not isinstance(ref, str) or not ref:
        raise ValueError("fresh baseline has no recorded image; refusing to re-pin")
    return {"ref": ref, "id": image.get("id"), "matches_pin": baseline.get("image_matches_pin")}


def check_baseline_workers(baseline: dict, workers: int, cell: str) -> None:
    """Refuse a worker count other than the fresh baseline's. A missing field warns.

    Baselines written before ``workers`` was recorded have no field. Those rows
    are not refused.
    """
    recorded = baseline.get("workers") if isinstance(baseline, dict) else None
    if isinstance(recorded, bool) or not isinstance(recorded, int):
        warnings.warn(
            f"{cell}: fresh baseline has no recorded workers (row predates the field); "
            f"not refusing workers={workers}",
            UserWarning, stacklevel=2)
        return
    if recorded != workers:
        raise ValueError(
            f"{cell}: refusing to run selection or confirmation with workers={workers}; "
            f"the fresh baseline recorded workers={recorded}")


def _trials_completed(child: Path) -> int:
    return len(rn.read_rows(Path(child) / "trials.jsonl"))


def _cap_fields(status: dict, trials_completed: int) -> dict | None:
    """Fields for an arm the cap stopped before N. ``None`` when the arm finished."""
    if not rn.is_cap_status(status):
        return None
    reason = status.get("stop_reason")
    if reason not in rn.CAP_STOP_REASONS:
        reason = "max_usd_per_cell"
    return {"stopped_by_cap": True, "stop_reason": reason, "stop_cell": status.get("cell"),
            "trials_completed": trials_completed, "max_usd": status.get("max_usd"),
            "max_usd_per_cell": status.get("max_usd_per_cell")}


def _arm(run_dir: Path, base_cfg: dict, proposal: dict, label: str, patched: bool, executor: rn.Executor,
         n_trials: int, spend_cap_usd: float | None, recorded_image: dict,
         arm_scope: str | None = None, workers: int = 1,
         ledger: rn.SpendLedger | None = None) -> tuple[dict, str, str, dict]:
    """One N-trial arm of one proposal: ``(summary row or {}, run state, relative dir)``.

    Each arm has its own run_id, so its trial ids are new and never reuse
    another arm's trials. The image is the fresh baseline's recorded image.
    Smoke compaction is off. A trial that reports a different image is refused.

    ``arm_scope`` separates two confirmation arms that share a ``proposal_id``
    (the same patch on two failures). Unset, the directory and run id stay
    ``ideation/<proposal_id>/<label>``.

    Returns ``(summary row or {}, run state, relative dir, status)``.
    ``spend_cap_usd`` is the per-cell cap (``max_usd_per_cell``) on the ledger
    when one is passed, and the runner's own ``spend_cap_usd`` otherwise.
    """
    if not isinstance(recorded_image, dict) or not recorded_image.get("ref"):
        raise ValueError("arm has no recorded image; refusing to re-pin")
    pid = proposal["proposal_id"]
    rel = f"ideation/{pid}/{label}"
    run_identity = pid
    if arm_scope:
        rel = f"ideation/{pid}/{arm_scope}/{label}"
        run_identity = f"{pid}--{arm_scope}"
    child = run_dir / rel
    _refuse_foreign_arm(child, proposal, label)
    previous = getattr(executor, "smoke_compaction", None)
    if previous:
        executor.smoke_compaction = False
    try:
        cell_cap = ledger.max_usd_per_cell if ledger is not None and ledger.max_usd_per_cell is not None else spend_cap_usd
        cfg = rn.RunConfig.from_dict({
            "run_id": f"{base_cfg['run_id']}--{label}--{run_identity}", "suite": base_cfg["suite"], "models": [proposal["model"]],
            "n_trials": n_trials, "tasks": [proposal["task"]], "max_rounds": 1, "fixed_tasks": True,
            "patch_id": pid if patched else None, "patch": proposal["patch"] if patched else None,
            "spend_cap_usd": cell_cap, "workers": workers,
            "smoke_compaction": False, "recorded_image": recorded_image})
        with rn.arm_lock() as lock:
            status = rn.Runner(cfg, child, executor, workers=workers, ledger=ledger).run()
            _stamp_arm_parent(child, proposal.get("parent_trial_id"))
            rn.stamp_arm_lock(child, lock, ledger)
            _check_fresh_image(f"{proposal['model']}/{proposal['task']}", child, recorded_image)
    finally:
        if previous:
            executor.smoke_compaction = previous
    rows = [s for s in rn.read_rows(child / "summary.jsonl")
            if s["patch_id"] == (pid if patched else None) and s["task"] == proposal["task"]]
    return (rows[0] if rows else {}), status["state"], rel, status


def _plan_str(value) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _plan_list(value) -> tuple:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _refuse_foreign_arm(child: Path, proposal: dict, label: str) -> None:
    """Refuse an arm directory whose ``plan.json`` belongs to a different arm.

    Compared fields are model, task, and ``parent_trial_id``. A missing
    ``parent_trial_id`` (the plan was written before the stamp) is not a
    difference. Selection of one patch on the same model and task is one
    directory for every failure of that patch: that resume is the ``confirm_k``
    1 layout, so a different parent there is not a new arm. Any other
    difference raises before the runner starts, and the directory is left
    unchanged.
    """
    path = child / "plan.json"
    if not path.is_file():
        return
    plan = json.loads(path.read_text(encoding="utf-8"))
    config = plan.get("config") if isinstance(plan.get("config"), dict) else {}
    recorded_models = _plan_list(config.get("models"))
    recorded_tasks = _plan_list(config.get("tasks"))
    recorded = (recorded_models, recorded_tasks, _plan_str(plan.get("parent_trial_id")))
    incoming = ((proposal.get("model"),), (proposal.get("task"),), _plan_str(proposal.get("parent_trial_id")))
    shared_selection = (label == "select" and recorded_models == incoming[0] and recorded_tasks == incoming[1])
    names = ("model", "task", "parent_trial_id")
    mismatched = []
    for name, was, now in zip(names, recorded, incoming):
        if was == now:
            continue
        if name == "parent_trial_id" and (was is None or shared_selection):
            continue
        mismatched.append(name)
    if not mismatched:
        return
    raise ValueError(
        f"refusing to reuse {child.name} under {child.parent.name}: plan.json "
        f"model={recorded_models!r} task={recorded_tasks!r} parent_trial_id={recorded[2]!r} "
        f"differs from this arm model={incoming[0]!r} task={incoming[1]!r} "
        f"parent_trial_id={incoming[2]!r} ({', '.join(mismatched)})")


def _stamp_arm_parent(child: Path, parent_trial_id) -> None:
    """Record ``parent_trial_id`` on the arm's ``plan.json`` once.

    The runner rewrites ``plan.json`` without this field. The first completed
    arm stamps it so a later arm can see whose directory this is. A stamp
    already present is left in place.
    """
    if not isinstance(parent_trial_id, str) or not parent_trial_id:
        return
    path = child / "plan.json"
    if not path.is_file():
        return
    plan = json.loads(path.read_text(encoding="utf-8"))
    if _plan_str(plan.get("parent_trial_id")) is not None:
        return
    plan["parent_trial_id"] = parent_trial_id
    rn._write_json(path, plan)


def _stage(prefix: str, baseline: dict, alt: dict, n: int) -> tuple[dict, float | None]:
    """Stage columns, and the alpha ``decide`` actually used."""
    d = decide(baseline, alt, n=n, alpha=ALPHA)
    return ({f"{prefix}_baseline_passes": baseline.get("passes"), f"{prefix}_baseline_completed": baseline.get("completed"),
             f"{prefix}_alt_passes": alt.get("passes"), f"{prefix}_alt_completed": alt.get("completed", 0),
             f"{prefix}_beats_baseline": d["beats_baseline"], f"{prefix}_complete": d["complete"],
             f"{prefix}_fisher_p": d["fisher_p"]}, d["alpha"])


def _require_alpha(alphas: list) -> float:
    """``evaluate`` writes a row only when every stage used 1.0."""
    if any(alpha != 1.0 for alpha in alphas):
        raise ValueError(f"refusing to write an ideation result with alpha {alphas}; evaluate always uses 1.0")
    return 1.0


def _require_arm_commit(child: Path, arm: str, baseline_commit: str) -> str:
    """The arm's ``code_commit``. Raises when it is missing or differs from ``baseline_commit``."""
    found: set[str] = set()
    plan_path = child / "plan.json"
    if plan_path.is_file():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        commit = (plan.get("code") or {}).get("commit")
        if isinstance(commit, str) and commit:
            found.add(commit)
    for table in ("trials.jsonl", "summary.jsonl"):
        for row in rn.read_rows(child / table):
            commit = row.get("code_commit")
            if isinstance(commit, str) and commit:
                found.add(commit)
    if not found:
        raise ValueError(f"{arm} recorded no code_commit")
    if found != {baseline_commit}:
        raise ValueError(f"{arm} code_commit {sorted(found)} differs from fresh baseline baseline_commit {baseline_commit}")
    return baseline_commit


def _require_baseline_commit(run_dir: Path, baseline: dict) -> str:
    """The fresh baseline's checkout. Its own ``code_commit`` must equal ``baseline_commit``."""
    commit = baseline.get("baseline_commit")
    recorded = baseline.get("code_commit")
    if not isinstance(commit, str) or not commit:
        raise ValueError("fresh baseline has no baseline_commit")
    if not isinstance(recorded, str) or not recorded:
        raise ValueError("fresh baseline recorded no code_commit")
    if recorded != commit:
        raise ValueError(f"fresh baseline code_commit {recorded} differs from baseline_commit {commit}")
    rel = baseline.get("run_dir")
    if rel:
        _require_arm_commit(Path(run_dir) / rel, "fresh baseline", commit)
    return commit


def _set_aside_count(summary: dict) -> int:
    """Set-aside trials in a runner summary row (the ``set_aside`` count, else blocked plus refused)."""
    if summary.get("set_aside") is not None:
        return int(summary["set_aside"])
    return int(summary.get("provider_blocked") or 0) + int(summary.get("model_refused") or 0)


def _candidate_rank(row: dict) -> tuple:
    """Lower is better. Highest passes, then earlier draw, then lower index, then proposal id.

    Fisher p is not in the key. Inside one cell the baseline is the same, so
    the same pass count is the same p. A missing pass count sorts last. A
    missing ``draw_order`` sorts after every seeded pick. A missing
    ``alternative_index`` sorts after every recorded index.
    """
    passes = row.get("selection_alt_passes")
    if isinstance(passes, bool) or not isinstance(passes, (int, float)):
        passes_rank = float("inf")
    else:
        passes_rank = -float(passes)
    order = row.get("draw_order")
    if isinstance(order, bool) or not isinstance(order, int):
        order_rank = 10**9
    else:
        order_rank = order
    index = row.get("alternative_index")
    if isinstance(index, bool) or not isinstance(index, int):
        index_rank = 10**9
    else:
        index_rank = index
    return (passes_rank, order_rank, index_rank, str(row.get("proposal_id") or ""))


def top_candidate(rows: list[dict]) -> dict | None:
    """The single best selection candidate of one cell, or None when ``rows`` has none.

    Tie-break, in order: higher ``selection_alt_passes``, earlier
    ``draw_order`` (the seeded pick in ``credit_draw.json``), lower
    ``alternative_index`` (the proposal's ``index``), then ``proposal_id``.
    ``selection_fisher_p`` is not a tie-break.
    """
    candidates = [row for row in rows if row.get("candidate")]
    if not candidates:
        return None
    return min(candidates, key=_candidate_rank)


def top_candidates(rows: list[dict], k: int) -> list[dict]:
    """The first ``k`` selection candidates of one cell, best first.

    The order is ``top_candidate``'s order. A cell with fewer than ``k``
    candidates returns all of them. ``selection_fisher_p`` is not a tie-break.
    """
    check_confirm_k(k)
    candidates = [row for row in rows if row.get("candidate")]
    return sorted(candidates, key=_candidate_rank)[:k]


def _model_task_of_draw_cell(cell: str) -> tuple[str, str]:
    """``model/task`` from a draw key. A ``@patch`` suffix is not part of the cell."""
    model, _, rest = cell.partition("/")
    return model, rest.split("@", 1)[0]


def _cell_draw_orders(run_dir: Path, model: str, task: str) -> dict[str, int]:
    """``trial_id -> draw_order`` for the drawn failures of one ``(model, task)`` cell."""
    orders: dict[str, int] = {}
    for pick in drawn_picks(run_dir):
        if _model_task_of_draw_cell(pick["cell"]) != (model, task):
            continue
        order = pick.get("draw_order")
        if isinstance(order, bool) or not isinstance(order, int):
            order = 10**9
        orders[pick["trial_id"]] = order
    return orders


def _load_results(run_dir: Path) -> list[dict]:
    return rn.read_rows(Path(run_dir) / "ideation_results.jsonl")


def _save_results(run_dir: Path, rows: list[dict]) -> None:
    path = Path(run_dir) / "ideation_results.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    os.replace(tmp, path)


def _append_result(run_dir: Path, row: dict) -> None:
    with (Path(run_dir) / "ideation_results.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _result_key(row: dict) -> tuple:
    """A result belongs to one failure. The same patch may share ``proposal_id`` across failures."""
    return (row.get("parent_trial_id"), row.get("proposal_id"))


def _accepted_proposal_ids(run_dir: Path, model: str, task: str, current: dict) -> tuple[set[tuple], set[str], set[str]]:
    """Accepted proposals across every drawn failure of one cell.

    Returns ``((parent trial, proposal id) pairs, drawn trial ids, parents
    that already have a proposal row)``. The same patch on two failures is
    two pairs: ``proposal_id`` is a hash of the patch and is not unique per
    failure. A drawn failure whose proposals were all rejected is accounted
    for and adds no accepted pair. The proposal being evaluated is included.
    """
    orders = _cell_draw_orders(run_dir, model, task)
    drawn_ids = set(orders)
    parent = current.get("parent_trial_id")
    if parent not in drawn_ids:
        raise ValueError(f"{model}/{task}: parent failure {parent} is not a drawn pick; "
                         "confirm=top ranks the cell's drawn failures")
    keys: set[tuple] = set()
    parents: set[str] = set()
    for row in rn.read_rows(Path(run_dir) / "ideation.jsonl"):
        if row.get("model") != model or row.get("task") != task:
            continue
        if row.get("parent_trial_id") not in drawn_ids:
            continue
        parents.add(row["parent_trial_id"])
        if row.get("status") != "accepted" or not row.get("proposal_id"):
            continue
        keys.add((row["parent_trial_id"], row["proposal_id"]))
    if current.get("proposal_id"):
        keys.add((parent, current["proposal_id"]))
    parents.add(parent)
    return keys, drawn_ids, parents


def _proposal_by_id(run_dir: Path, proposal_id: str, current: dict, parent_trial_id: str | None = None) -> dict:
    def matches(row: dict) -> bool:
        if row.get("proposal_id") != proposal_id:
            return False
        return parent_trial_id is None or row.get("parent_trial_id") == parent_trial_id

    if matches(current):
        return current
    for row in rn.read_rows(Path(run_dir) / "ideation.jsonl"):
        if matches(row):
            return row
    raise ValueError(f"no proposal {proposal_id} for failure {parent_trial_id} in ideation.jsonl")


def _skip_not_top(row: dict) -> None:
    """A selection candidate outside the confirmed set under ``confirm=top``."""
    row.update(
        confirmation_baseline_passes=None, confirmation_baseline_completed=None,
        confirmation_alt_passes=None, confirmation_alt_completed=None,
        confirmation_beats_baseline=None, confirmation_complete=None, confirmation_fisher_p=None,
        confirmation_spend_usd=None, confirmation_run_dirs=None, confirmation_run_states=None,
        confirmation_code_commit=None, confirmation_baseline_code_commit=None,
        confirmed=None, success=False, confirm_skipped=CONFIRM_SKIPPED_NOT_TOP)


def _mark_unconfirmed(row: dict, cap: dict, spend: float, dirs: list, states: list,
                      alt_commit: str | None, base_commit: str | None) -> dict:
    """A confirmation the cap stopped partway. The candidate stays unconfirmed.

    ``decide`` is not called. ``confirmed`` stays null, so this is not a loss.
    """
    row.update(cap, confirmed=None, success=None, confirm_skipped=None,
               confirmation_baseline_passes=None, confirmation_baseline_completed=None,
               confirmation_alt_passes=None, confirmation_alt_completed=None,
               confirmation_beats_baseline=None, confirmation_complete=None, confirmation_fisher_p=None,
               confirmation_spend_usd=round(spend, 6), confirmation_run_dirs=dirs, confirmation_run_states=states,
               confirmation_code_commit=alt_commit, confirmation_baseline_code_commit=base_commit)
    return row


def _run_confirmation(run_dir: Path, base_cfg: dict, proposal: dict, row: dict, executor: rn.Executor,
                      n_trials: int, spend_cap_usd: float | None, recorded: dict, baseline_commit: str,
                      alphas: list, arm_scope: str | None = None, workers: int = 1,
                      ledger: rn.SpendLedger | None = None) -> dict:
    """Fresh confirmation arms. Raises before the result row is replaced when a check fails.

    Each call runs a new alternative and a new baseline. ``arm_scope`` keeps
    those arms distinct when two confirmed candidates share a proposal id.
    A cap that stops either arm leaves the candidate unconfirmed and does not
    call ``decide``. The confirmation baseline is not started when the
    alternative arm already stopped for a cap.
    """
    conf_alt, alt_state, alt_dir, alt_status = _arm(
        run_dir, base_cfg, proposal, "confirm", True, executor, n_trials,
        spend_cap_usd, recorded, arm_scope=arm_scope, workers=workers, ledger=ledger)
    conf_commit = _require_arm_commit(run_dir / alt_dir, "confirmation", baseline_commit)
    alt_cap = _cap_fields(alt_status, _trials_completed(run_dir / alt_dir))
    if alt_cap:
        if alt_cap.get("stop_cell") is None:
            alt_cap["stop_cell"] = f"{proposal['model']}/{proposal['task']}"
        return _mark_unconfirmed(row, alt_cap, conf_alt.get("spend_usd", 0.0), [alt_dir], [alt_state],
                                 conf_commit, None)
    conf_base, base_state, base_dir, base_status = _arm(
        run_dir, base_cfg, proposal, "confirm-baseline", False, executor,
        n_trials, spend_cap_usd, recorded, arm_scope=arm_scope, workers=workers, ledger=ledger)
    base_commit = _require_arm_commit(run_dir / base_dir, "confirmation-baseline", baseline_commit)
    base_cap = _cap_fields(base_status, _trials_completed(run_dir / base_dir))
    if base_cap:
        if base_cap.get("stop_cell") is None:
            base_cap["stop_cell"] = f"{proposal['model']}/{proposal['task']}"
        spend = conf_alt.get("spend_usd", 0.0) + conf_base.get("spend_usd", 0.0)
        return _mark_unconfirmed(row, base_cap, spend, [alt_dir, base_dir], [alt_state, base_state],
                                 conf_commit, base_commit)
    confirmation, conf_alpha = _stage("confirmation", conf_base, conf_alt, n_trials)
    alphas.append(conf_alpha)
    confirmed = confirmation["confirmation_complete"] and confirmation["confirmation_beats_baseline"]
    row.update(confirmation, confirmed=confirmed, success=confirmed, confirm_skipped=None,
               confirmation_spend_usd=round(conf_alt.get("spend_usd", 0.0) + conf_base.get("spend_usd", 0.0), 6),
               confirmation_run_dirs=[alt_dir, base_dir], confirmation_run_states=[alt_state, base_state],
               confirmation_code_commit=conf_commit, confirmation_baseline_code_commit=base_commit)
    row["alpha"] = _require_alpha(alphas)
    return row


def _confirm_top(run_dir: Path, base_cfg: dict, proposal: dict, row: dict, executor: rn.Executor,
                 n_trials: int, spend_cap_usd: float | None, recorded: dict, baseline_commit: str,
                 confirm_k: int = DEFAULT_CONFIRM_K, workers: int = 1,
                 ledger: rn.SpendLedger | None = None) -> dict:
    """Confirm the top ``confirm_k`` candidates once every drawn failure is selected.

    The cell is ``(model, task)``. The set is every accepted alternative of
    that cell's drawn failures, not one parent failure. Until every drawn
    failure has a proposal row and every accepted proposal has a selection
    row, this row is stored with confirmation fields null. When the set
    completes, the top ``confirm_k`` candidates (or every candidate, when the
    cell has fewer) are each confirmed on a fresh baseline. Every other
    candidate in the cell is ``confirm_skipped: not_top`` with ``candidate``
    left true. ``confirm_k`` 1 uses ``top_candidate``. Each winner is written
    to ``ideation_results.jsonl`` as soon as its confirmation returns. A later
    confirmation that raises leaves the earlier rows in place and does not
    start the confirmations after it.
    """
    model, task = row["model"], row["task"]
    # The same patch hashes to one proposal_id. Keep the other failure's row.
    results = [item for item in _load_results(run_dir) if _result_key(item) != _result_key(row)]
    results.append(row)
    accepted, drawn_ids, parents = _accepted_proposal_ids(run_dir, model, task, proposal)
    if not drawn_ids <= parents:
        _save_results(run_dir, results)
        return row
    have = {_result_key(item) for item in results
            if item.get("model") == model and item.get("task") == task
            and item.get("parent_trial_id") in drawn_ids and item.get("proposal_id")}
    if not accepted <= have:
        _save_results(run_dir, results)
        return row
    group = [item for item in results
             if item.get("model") == model and item.get("task") == task and item.get("parent_trial_id") in drawn_ids]
    if confirm_k == 1:
        picked = top_candidate(group)
        winners = [] if picked is None else [picked]
    else:
        winners = top_candidates(group, confirm_k)
    if not winners:
        _save_results(run_dir, results)
        return row
    winner_keys = {_result_key(item) for item in winners}
    for item in group:
        if item.get("candidate") and _result_key(item) not in winner_keys:
            _skip_not_top(item)
    pid_counts: dict[str, int] = {}
    for item in winners:
        pid_counts[item["proposal_id"]] = pid_counts.get(item["proposal_id"], 0) + 1
    confirmed_by_key = {}
    for winner in winners:
        winner_proposal = _proposal_by_id(run_dir, winner["proposal_id"], proposal, winner.get("parent_trial_id"))
        scope = winner.get("parent_trial_id") if pid_counts[winner["proposal_id"]] > 1 else None
        confirmed = _run_confirmation(
            run_dir, base_cfg, winner_proposal, dict(winner), executor, n_trials, spend_cap_usd, recorded,
            baseline_commit, [winner.get("alpha", ALPHA)], arm_scope=scope, workers=workers, ledger=ledger)
        confirmed_by_key[_result_key(winner)] = confirmed
        results = [confirmed_by_key.get(_result_key(item), item) for item in results]
        _save_results(run_dir, results)
        if confirmed.get("stopped_by_cap"):
            break  # this cell (or the invocation) is done spending; later winners are not started
    return next(item for item in results if _result_key(item) == _result_key(row))


def evaluate(run_dir: Path, proposal: dict, executor: rn.Executor, n_trials: int = rn.N_TRIALS,
             spend_cap_usd: float | None = None, max_set_aside: int = MAX_SET_ASIDE,
             confirm: str = CONFIRM_ALL, confirm_k: int = DEFAULT_CONFIRM_K,
             max_usd: float | None = None, workers: int = 1,
             ledger: rn.SpendLedger | None = None) -> dict:
    """Two-stage evaluation of one accepted proposal (João Sedoc via Sean, SEA-110).

    1. **Selection:** the alternative runs N trials. It is a *candidate* iff
       both it and the fresh baseline completed N and it has more passes
       (bare beat, no significance gate; 1/30 vs 0/30 qualifies; a tie does not).
       The fresh baseline is ``credit_baseline.json``. A cell without one is
       an error. The pilot ``summary.jsonl`` row is not read.
    2. **Confirmation** (candidates only): a fresh N-trial run of the
       alternative **and** a new fresh N-trial baseline run (no patch), both with
       new run ids, so new trial ids, and no reuse of the selection trials or
       of the selection baseline. ``success`` iff the alternative beats that
       new baseline (bare beat, full N on both sides).

    ``confirm`` is ``all`` (default) or ``top``. ``all`` confirms every
    selection candidate. ``top`` confirms ``confirm_k`` candidates per cell
    ``(model, task)`` (default 1), across that cell's drawn failures: highest
    ``selection_alt_passes``, then earlier ``draw_order`` from
    ``credit_draw.json``, then lower ``alternative_index``, then
    ``proposal_id``. Fisher p is not a tie-break. A cell with fewer than
    ``confirm_k`` candidates confirms all of them. Other candidates in the
    cell stay candidates, with ``confirm_skipped: not_top`` and confirmation
    fields null. The choice waits until every drawn failure has a proposal
    row and every accepted proposal has a selection row; until then the cell
    stays unconfirmed. ``confirm`` and ``confirm_k`` are stored on every
    result row. ``confirm_k`` must be an int >= 1, and a value other than 1
    is an error when ``confirm`` is ``all``.

    The one-sided Fisher p for each stage is recorded as a reported statistic
    only. ``evaluate`` does not take ``alpha`` and always uses ``ALPHA`` (1.0).
    A row whose alpha is not 1.0 is not written, except a cap stop: that row
    is unresolved (``stopped_by_cap``, ``alpha`` null) and ``decide`` is not
    called on the partial arm. ``spend_cap_usd`` is ``max_usd_per_cell``: the
    runner's spend check for the ``(model, task)`` cell, shared across this
    invocation's arms of that cell. ``max_usd`` is the invocation total. A
    partial confirmation leaves the candidate unconfirmed (``confirmed`` null),
    not failed. Every arm reuses the fresh baseline's recorded image, with smoke
    compaction off, and records ``code_commit``. An arm whose ``code_commit``
    differs from the fresh baseline's ``baseline_commit`` is refused.
    ``workers`` must match the fresh baseline's recorded ``workers`` (default
    1). A baseline row from before that field warns and is not refused.
    The cell is evaluated when the fresh baseline's set-aside
    count is at most ``max_set_aside`` (default 3, about 10% of 30), the same
    cap as credit assignment."""
    mode = check_confirm(confirm)
    k = check_confirm_k(confirm_k, mode)
    workers = rn.check_workers(workers)
    spend_cap_usd = rn.check_optional_usd("max_usd_per_cell", spend_cap_usd)
    max_usd = rn.check_optional_usd("max_usd", max_usd)
    if proposal["status"] != "accepted":
        raise ValueError("only accepted proposals are evaluated")
    run_dir = Path(run_dir)
    base_cfg = json.loads((run_dir / "plan.json").read_text())["config"]
    # The pilot summary row is retired. Do not fall back to it when this raises.
    baseline = fresh_baseline_row(run_dir, proposal["task"], proposal["model"])
    cell_name = f"{proposal['model']}/{proposal['task']}"
    if baseline.get("stopped_by_cap"):
        raise ValueError(f"{cell_name}: fresh baseline was stopped_by_cap at "
                         f"{baseline.get('trials_completed')} trials; refusing to score")
    check_baseline_workers(baseline, workers, cell_name)
    if ledger is None and (spend_cap_usd is not None or max_usd is not None):
        ledger = rn.SpendLedger(max_usd=max_usd, max_usd_per_cell=spend_cap_usd)
    if ledger is not None:
        ledger.seed_run(run_dir)
    max_set_aside = check_max_set_aside(max_set_aside)
    aside = _set_aside_count(baseline)
    # Amended Researcher ruling 2026-11-17: a cell enters when its set-aside count is at most max_set_aside
    # (default 3, about 10% of 30). The count is the fresh baseline's, not the old summary row.
    if aside > max_set_aside:
        raise ValueError(f"{proposal['task']} / {proposal['model']} has {aside} set-aside trials "
                         f"(max_set_aside {max_set_aside}); not evaluated")
    if proposal.get("uncited"):
        raise ValueError("uncited proposal is not evaluated")
    baseline_commit = _require_baseline_commit(run_dir, baseline)
    recorded = _recorded_image(baseline)
    draw_order = None
    if mode == CONFIRM_TOP:
        orders = _cell_draw_orders(run_dir, proposal["model"], proposal["task"])
        parent = proposal.get("parent_trial_id")
        if parent not in orders:
            raise ValueError(f"{proposal['model']}/{proposal['task']}: parent failure {parent} is not a drawn pick; "
                             "confirm=top ranks the cell's drawn failures")
        draw_order = orders[parent]
    sel_alt, sel_state, sel_dir, sel_status = _arm(
        run_dir, base_cfg, proposal, "select", True, executor, n_trials, spend_cap_usd,
        recorded, workers=workers, ledger=ledger)
    sel_commit = _require_arm_commit(run_dir / sel_dir, "selection", baseline_commit)
    sel_cap = _cap_fields(sel_status, _trials_completed(run_dir / sel_dir))
    if sel_cap is not None:
        # Partial selection is unresolved. decide does not run, so this is not a non-candidate.
        if sel_cap.get("stop_cell") is None:
            sel_cap["stop_cell"] = cell_name
        row = {"schema": RESULT_SCHEMA, "proposal_id": proposal["proposal_id"],
               "parent_trial_id": proposal["parent_trial_id"],
               "task": proposal["task"], "model": proposal["model"], "credit_method": proposal["credit_method"],
               "citations": proposal.get("citations"), "uncited": bool(proposal.get("uncited")),
               "alternative_index": proposal.get("index"), "draw_order": draw_order,
               "confirm": mode, "confirm_k": k, "confirm_skipped": None,
               "n_trials": n_trials, "baseline_commit": baseline_commit, "code_commit": baseline_commit,
               "selection_baseline_passes": None, "selection_baseline_completed": None,
               "selection_alt_passes": None, "selection_alt_completed": None,
               "selection_beats_baseline": None, "selection_complete": None, "selection_fisher_p": None,
               "candidate": None, "selection_spend_usd": sel_alt.get("spend_usd", 0.0),
               "selection_run_dir": sel_dir, "selection_run_state": sel_state, "selection_code_commit": sel_commit,
               "confirmation_baseline_passes": None, "confirmation_baseline_completed": None,
               "confirmation_alt_passes": None, "confirmation_alt_completed": None,
               "confirmation_beats_baseline": None,
               "confirmation_complete": None, "confirmation_fisher_p": None, "confirmation_spend_usd": 0.0,
               "confirmation_run_dirs": None, "confirmation_run_states": None,
               "confirmation_code_commit": None, "confirmation_baseline_code_commit": None,
               "confirmed": None, "success": None, "alpha": None, **sel_cap}
        _append_result(run_dir, row)
        return row
    selection, sel_alpha = _stage("selection", baseline, sel_alt, n_trials)
    candidate = selection["selection_complete"] and selection["selection_beats_baseline"]
    alphas = [sel_alpha]
    row = {"schema": RESULT_SCHEMA, "proposal_id": proposal["proposal_id"], "parent_trial_id": proposal["parent_trial_id"],
           "task": proposal["task"], "model": proposal["model"], "credit_method": proposal["credit_method"],
           "citations": proposal.get("citations"), "uncited": bool(proposal.get("uncited")),
           "alternative_index": proposal.get("index"), "draw_order": draw_order,
           "confirm": mode, "confirm_k": k, "confirm_skipped": None,
           "n_trials": n_trials, "baseline_commit": baseline_commit, "code_commit": baseline_commit, **selection,
           "candidate": candidate, "selection_spend_usd": sel_alt.get("spend_usd", 0.0),
           "selection_run_dir": sel_dir, "selection_run_state": sel_state, "selection_code_commit": sel_commit,
           "confirmation_baseline_passes": None, "confirmation_baseline_completed": None,
           "confirmation_alt_passes": None, "confirmation_alt_completed": None, "confirmation_beats_baseline": None,
           "confirmation_complete": None, "confirmation_fisher_p": None, "confirmation_spend_usd": 0.0,
           "confirmation_run_dirs": None, "confirmation_run_states": None,
           "confirmation_code_commit": None, "confirmation_baseline_code_commit": None,
           "confirmed": None, "success": False}
    if candidate and mode == CONFIRM_ALL:
        row = _run_confirmation(run_dir, base_cfg, proposal, row, executor, n_trials, spend_cap_usd, recorded,
                                baseline_commit, alphas, workers=workers, ledger=ledger)
    elif mode == CONFIRM_TOP:
        row["alpha"] = _require_alpha(alphas)
        return _confirm_top(run_dir, base_cfg, proposal, row, executor, n_trials, spend_cap_usd, recorded,
                            baseline_commit, confirm_k=k, workers=workers, ledger=ledger)
    else:
        row["alpha"] = _require_alpha(alphas)
    _append_result(run_dir, row)
    return row


@dataclass
class VertexClaudeIdeator:
    """Ideator on Vertex Anthropic ``rawPredict`` (ADC), thinking set explicitly."""
    project: str
    token: Callable[[], str]
    model_id: str = IDEATOR_MODEL
    opener: Callable = urllib.request.urlopen

    def request_body(self, prompt: str) -> dict:
        return {"anthropic_version": "vertex-2023-10-16", "max_tokens": 16000, "thinking": dict(IDEATOR_THINKING),
                "messages": [{"role": "user", "content": prompt}]}

    def propose(self, prompt: str) -> tuple[str, dict | None]:
        url = (f"https://aiplatform.googleapis.com/v1/projects/{self.project}/locations/global/publishers/anthropic/"
               f"models/{self.model_id}:rawPredict")
        req = urllib.request.Request(url, data=json.dumps(self.request_body(prompt)).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token()}"})
        with self.opener(req, timeout=600) as resp:
            doc = json.loads(resp.read())
        text = "".join(b.get("text", "") for b in doc.get("content") or [] if b.get("type") == "text")
        start, end = text.find("{"), text.rfind("}")
        return (text[start:end + 1] if start >= 0 else text), doc.get("usage")


def main(argv: list[str] | None = None) -> int:
    """Evaluate accepted proposals. The only executor is the offline ``--fixture`` table.

    This command does not start a provider. ``--confirm`` and ``--confirm-k`` override ``--config``.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate accepted ideation proposals (offline fixture only)")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="IdeationConfig JSON (confirm: top|all, confirm_k)")
    parser.add_argument("--confirm", choices=list(CONFIRM_MODES), default=None,
                        help="which selection candidates to confirm (default all; overrides --config)")
    parser.add_argument("--confirm-k", type=int, default=None,
                        help="how many candidates confirm=top confirms per cell (default 1; overrides --config)")
    parser.add_argument("--fixture", type=Path, required=True,
                        help='offline pass table {"task|model": passes}. This command does not call a provider.')
    parser.add_argument("--n-trials", type=int, default=rn.N_TRIALS)
    parser.add_argument("--max-set-aside", type=int, default=MAX_SET_ASIDE)
    parser.add_argument("--max-usd", type=rn.positive_usd_arg, default=None,
                        help="stop the invocation before the trial that would pass this total (optional, > 0)")
    parser.add_argument("--max-usd-per-cell", type=rn.positive_usd_arg, default=None,
                        help="per (model, task) cell cap; maps to spend_cap_usd (optional, > 0). "
                             "Other cells continue. Intended use: 1.5x that cell's estimate")
    parser.add_argument("--workers", type=rn.positive_workers_arg, default=1,
                        help="trials of one arm at once (default 1). Arms run one at a time")
    args = parser.parse_args(argv)
    if isinstance(args.n_trials, bool) or args.n_trials < 1:
        raise SystemExit("n-trials must be a positive integer")
    try:
        cfg = resolve_config(args.config, args.confirm, args.confirm_k)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    raw = json.loads(args.fixture.read_text(encoding="utf-8"))
    executor = rn.FixtureExecutor({tuple(k.split("|", 1)): int(v) for k, v in raw.items()})
    proposals = [row for row in rn.read_rows(args.run / "ideation.jsonl") if row.get("status") == "accepted"]
    proposals.sort(key=lambda row: (row.get("parent_trial_id") or "", row.get("index") is None,
                                    row.get("index") if isinstance(row.get("index"), int) else 0,
                                    row.get("proposal_id") or ""))
    ledger = None
    if args.max_usd is not None or args.max_usd_per_cell is not None:
        ledger = rn.SpendLedger(max_usd=args.max_usd, max_usd_per_cell=args.max_usd_per_cell)
        ledger.seed_run(args.run)
    try:
        for proposal in proposals:
            if ledger is not None and ledger.invocation_stop == "max_usd":
                break
            evaluate(args.run, proposal, executor, n_trials=args.n_trials,
                     spend_cap_usd=args.max_usd_per_cell, max_usd=args.max_usd,
                     max_set_aside=args.max_set_aside, confirm=cfg.confirm, confirm_k=cfg.confirm_k,
                     workers=args.workers, ledger=ledger)
    except (ValueError, rn.RunnerError, BaselineError) as exc:
        raise SystemExit(str(exc)) from None
    rows = rn.read_rows(args.run / "ideation_results.jsonl")
    cell_stops = [{"cell": row.get("stop_cell") or f"{row.get('model')}/{row.get('task')}",
                   "stop_reason": row.get("stop_reason"), "trials_completed": row.get("trials_completed"),
                   "proposal_id": row.get("proposal_id")}
                  for row in rows if row.get("stopped_by_cap")]
    if ledger is not None and ledger.invocation_stop == "max_usd":
        stop_reason = "max_usd"
    elif cell_stops:
        stop_reason = "max_usd_per_cell"
    else:
        stop_reason = None
    print(json.dumps({
        "confirm": cfg.confirm, "confirm_k": cfg.confirm_k, "evaluated": len(rows),
        "workers": args.workers, "max_usd": args.max_usd, "max_usd_per_cell": args.max_usd_per_cell,
        "stop_reason": stop_reason, "stopped_cells": cell_stops,
        "candidates": sum(1 for row in rows if row.get("candidate")),
        "confirmed": sum(1 for row in rows if row.get("confirmed")),
        "confirm_skipped": sum(1 for row in rows if row.get("confirm_skipped")),
        "stopped_by_cap": len(cell_stops),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
