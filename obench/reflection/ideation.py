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
  baseline again.

Both stages record the one-sided Fisher exact p as a reported statistic only.
``evaluate`` does not take ``alpha`` and always uses ``ALPHA`` (1.0). It
refuses to write a row whose alpha is not 1.0. ``decide(alpha=...)`` remains
for a library check. A p-gated view is a report column computed from the
recorded Fisher p and does not change ``candidate``, ``confirmed``, or
``success``. Each arm reuses the fresh baseline's recorded image, with smoke
compaction off.
``runner.ideation_estimate`` prices selection plus confirmation.

Tables (in the run directory, separate from the trial and credit tables):
``ideation.jsonl`` (proposals) and ``ideation_results.jsonl`` (one row per
evaluated proposal).
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from obench.reflection import runner as rn
from obench.reflection.credit_baseline import _check_fresh_image, fresh_baseline_row
from obench.reflection.credit_locator import MAX_SET_ASIDE, check_max_set_aside, read_trace
from obench.reflection.patches import OPS, PATCH_SCHEMA, patch_id, validate_patch

N_ALTERNATIVES = 5
ALPHA = 1.0   # no significance gate (Sean, 2026-11-13); fisher_p is still reported
PROMPT_VERSION = "I1"
PROPOSAL_SCHEMA = "openbench.reflection.ideation/v1"
RESULT_SCHEMA = "openbench.reflection.ideation_result/v1"
CREDIT_METHODS = ("A", "B", "A+B")
IDEATOR_MODEL = "claude-opus-5-5"              # open: configurable; not the model under test by design
IDEATOR_THINKING = {"type": "adaptive"}        # set explicitly on every ideator request


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
    """Prompt version ``PROMPT_VERSION`` (deterministic for the same inputs)."""
    tools = sorted({c.get("name") for s in steps for c in s.get("tool_calls") or [] if c.get("name")})
    spec = {op: sorted(fields) for op, fields in OPS.items()}
    return (
        "A coding agent failed a task. Credit assignment located where it went wrong (below). Propose exactly "
        f"{N_ALTERNATIVES} alternative changes that might make the agent succeed. You may ONLY change the agent's "
        "system prompt or its tools' descriptions / parameter descriptions. No code changes, no task or checker "
        "changes, no model or sampling changes.\n"
        f"Each alternative is a patch: {{\"schema\": \"{PATCH_SCHEMA}\", \"ops\": [...]}} with ops from {json.dumps(spec)}. "
        f"Tools seen in this trace: {tools}.\n"
        "Answer with JSON only: {\"alternatives\": [{\"rationale\": <why>, \"patch\": <patch>}, ...]}.\n\n"
        + json.dumps({"task": trial["task"], "model": trial["model"], "credit": credit, "trace": _digest(steps)},
                     sort_keys=True, indent=1))


def _credit_for(run_dir: Path, trial_id: str, method: str) -> dict:
    out = {}
    for m, table in (("A", "credit_a.jsonl"), ("B", "credit_b.jsonl")):
        if m not in method:
            continue
        rows = [r for r in rn.read_rows(run_dir / table) if r["trial_id"] == trial_id]
        if not rows:
            raise ValueError(f"no Method {m} row for trial {trial_id} in {table}")
        r = rows[0]
        out[m] = ({"failing_step": r["failing_step"], "signal": r["signal"], "rationale": r["rationale"],
                   "evidence": r["evidence"], "rule_version": r["rule_version"]} if m == "A" else
                  {"first_failing_step": r["first_failing_step"], "weights": r["weights"], "labels": r["labels"],
                   "prompt_version": r["prompt_version"], "system1_model": r["system1_model"]})
    return out


def parse_alternatives(raw: str) -> list[dict]:
    doc = json.loads(raw)
    alts = doc.get("alternatives")
    if not isinstance(alts, list):
        raise ValueError("no 'alternatives' list")
    return alts


def propose(run_dir: Path, trial: dict, method: str, ideator: Ideator, max_asks: int = 2) -> list[dict]:
    """Proposal rows for one failed trial (appended to ``ideation.jsonl``)."""
    if method not in CREDIT_METHODS:
        raise ValueError(f"credit method must be one of {CREDIT_METHODS}")
    run_dir = Path(run_dir)
    steps = read_trace(run_dir / trial["trace"]) if trial.get("trace") else []
    credit = _credit_for(run_dir, trial["trial_id"], method)
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
        if not problems:
            break
    rows = []
    for i, alt in enumerate(alts):
        patch = (alt or {}).get("patch") if isinstance(alt, dict) else None
        reasons = validate_patch(patch)
        rows.append({
            "schema": PROPOSAL_SCHEMA, "prompt_version": PROMPT_VERSION, "ideator_model": ideator.model_id,
            "run_id": trial.get("run_id"), "parent_trial_id": trial["trial_id"], "task": trial["task"],
            "model": trial["model"], "credit_method": method,
            "credit_rows": {m: f"{'credit_a' if m == 'A' else 'credit_b'}.jsonl#{trial['trial_id']}" for m in credit},
            "index": i, "rationale": (alt or {}).get("rationale") if isinstance(alt, dict) else None,
            "patch": patch, "proposal_id": patch_id(patch) if not reasons else None,
            "status": "accepted" if not reasons else "rejected", "rejection_reasons": reasons,
            "complete_set": len(alts) == N_ALTERNATIVES, "raw_ideator_output": raw, "ideator_usage": usage,
        })
    with (run_dir / "ideation.jsonl").open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
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


def _arm(run_dir: Path, base_cfg: dict, proposal: dict, label: str, patched: bool, executor: rn.Executor,
         n_trials: int, spend_cap_usd: float | None, recorded_image: dict) -> tuple[dict, str, str]:
    """One N-trial arm of one proposal: ``(summary row or {}, run state, relative dir)``.

    Each arm has its own run_id, so its trial ids are new and never reuse
    another arm's trials. The image is the fresh baseline's recorded image.
    Smoke compaction is off. A trial that reports a different image is refused.
    """
    if not isinstance(recorded_image, dict) or not recorded_image.get("ref"):
        raise ValueError("arm has no recorded image; refusing to re-pin")
    pid = proposal["proposal_id"]
    rel = f"ideation/{pid}/{label}"
    child = run_dir / rel
    previous = getattr(executor, "smoke_compaction", None)
    if previous:
        executor.smoke_compaction = False
    try:
        cfg = rn.RunConfig.from_dict({
            "run_id": f"{base_cfg['run_id']}--{label}--{pid}", "suite": base_cfg["suite"], "models": [proposal["model"]],
            "n_trials": n_trials, "tasks": [proposal["task"]], "max_rounds": 1, "fixed_tasks": True,
            "patch_id": pid if patched else None, "patch": proposal["patch"] if patched else None,
            "spend_cap_usd": spend_cap_usd, "smoke_compaction": False, "recorded_image": recorded_image})
        status = rn.Runner(cfg, child, executor).run()
        _check_fresh_image(f"{proposal['model']}/{proposal['task']}", child, recorded_image)
    finally:
        if previous:
            executor.smoke_compaction = previous
    rows = [s for s in rn.read_rows(child / "summary.jsonl")
            if s["patch_id"] == (pid if patched else None) and s["task"] == proposal["task"]]
    return (rows[0] if rows else {}), status["state"], rel


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


def _set_aside_count(summary: dict) -> int:
    """Set-aside trials in a runner summary row (the ``set_aside`` count, else blocked plus refused)."""
    if summary.get("set_aside") is not None:
        return int(summary["set_aside"])
    return int(summary.get("provider_blocked") or 0) + int(summary.get("model_refused") or 0)


def evaluate(run_dir: Path, proposal: dict, executor: rn.Executor, n_trials: int = rn.N_TRIALS,
             spend_cap_usd: float | None = None, max_set_aside: int = MAX_SET_ASIDE) -> dict:
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

    The one-sided Fisher p for each stage is recorded as a reported statistic
    only. ``evaluate`` does not take ``alpha`` and always uses ``ALPHA`` (1.0).
    A row whose alpha is not 1.0 is not written. ``spend_cap_usd`` applies to
    each arm. Every arm reuses the fresh baseline's recorded image, with smoke
    compaction off. The cell is evaluated when the fresh baseline's set-aside
    count is at most ``max_set_aside`` (default 3, about 10% of 30), the same
    cap as credit assignment."""
    if proposal["status"] != "accepted":
        raise ValueError("only accepted proposals are evaluated")
    run_dir = Path(run_dir)
    base_cfg = json.loads((run_dir / "plan.json").read_text())["config"]
    # The pilot summary row is retired. Do not fall back to it when this raises.
    baseline = fresh_baseline_row(run_dir, proposal["task"], proposal["model"])
    max_set_aside = check_max_set_aside(max_set_aside)
    aside = _set_aside_count(baseline)
    # Amended Researcher ruling 2026-11-17: a cell enters when its set-aside count is at most max_set_aside
    # (default 3, about 10% of 30). The count is the fresh baseline's, not the old summary row.
    if aside > max_set_aside:
        raise ValueError(f"{proposal['task']} / {proposal['model']} has {aside} set-aside trials "
                         f"(max_set_aside {max_set_aside}); not evaluated")
    recorded = _recorded_image(baseline)
    sel_alt, sel_state, sel_dir = _arm(run_dir, base_cfg, proposal, "select", True, executor, n_trials, spend_cap_usd,
                                       recorded)
    selection, sel_alpha = _stage("selection", baseline, sel_alt, n_trials)
    candidate = selection["selection_complete"] and selection["selection_beats_baseline"]
    alphas = [sel_alpha]
    row = {"schema": RESULT_SCHEMA, "proposal_id": proposal["proposal_id"], "parent_trial_id": proposal["parent_trial_id"],
           "task": proposal["task"], "model": proposal["model"], "credit_method": proposal["credit_method"],
           "n_trials": n_trials, "baseline_commit": baseline.get("baseline_commit"), **selection,
           "candidate": candidate, "selection_spend_usd": sel_alt.get("spend_usd", 0.0),
           "selection_run_dir": sel_dir, "selection_run_state": sel_state,
           "confirmation_baseline_passes": None, "confirmation_baseline_completed": None,
           "confirmation_alt_passes": None, "confirmation_alt_completed": None, "confirmation_beats_baseline": None,
           "confirmation_complete": None, "confirmation_fisher_p": None, "confirmation_spend_usd": 0.0,
           "confirmation_run_dirs": None, "confirmation_run_states": None, "confirmed": None, "success": False}
    if candidate:
        conf_alt, alt_state, alt_dir = _arm(run_dir, base_cfg, proposal, "confirm", True, executor, n_trials,
                                            spend_cap_usd, recorded)
        conf_base, base_state, base_dir = _arm(run_dir, base_cfg, proposal, "confirm-baseline", False, executor,
                                               n_trials, spend_cap_usd, recorded)
        confirmation, conf_alpha = _stage("confirmation", conf_base, conf_alt, n_trials)
        alphas.append(conf_alpha)
        confirmed = confirmation["confirmation_complete"] and confirmation["confirmation_beats_baseline"]
        row.update(confirmation, confirmed=confirmed, success=confirmed,
                   confirmation_spend_usd=round(conf_alt.get("spend_usd", 0.0) + conf_base.get("spend_usd", 0.0), 6),
                   confirmation_run_dirs=[alt_dir, base_dir], confirmation_run_states=[alt_state, base_state])
    row["alpha"] = _require_alpha(alphas)
    with (run_dir / "ideation_results.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
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
