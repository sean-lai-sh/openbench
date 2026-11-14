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
by the recording proxy. ``decide`` compares it with the baseline summary row
(same task, model, N). The success rule (Sean, 2026-11-13) is in ``decide``:
- ``success``: both sides completed all N trials **and** the alternative has
  more passes than the baseline. 1/30 vs 0/30 counts. Nothing short of N
  completed trials on both sides is judged.
- ``fisher_p``: the one-sided Fisher exact p-value, recorded on every row as
  a reported statistic. It does not gate success (``ALPHA = 1.0``). Passing a
  smaller ``alpha`` to ``decide`` re-enables a significance gate for
  sensitivity analysis.

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
from obench.reflection.credit_locator import read_trace
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


def decide(baseline: dict, alternative: dict, n: int = rn.N_TRIALS, alpha: float = ALPHA) -> dict:
    """The success rule. Both summary rows must have completed all ``n`` trials."""
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


def evaluate(run_dir: Path, proposal: dict, executor: rn.Executor, n_trials: int = rn.N_TRIALS,
             spend_cap_usd: float | None = None) -> dict:
    """Run one accepted proposal at N through the runner, then decide."""
    if proposal["status"] != "accepted":
        raise ValueError("only accepted proposals are evaluated")
    run_dir = Path(run_dir)
    base_cfg = json.loads((run_dir / "plan.json").read_text())["config"]
    baseline = [s for s in rn.read_rows(run_dir / "summary.jsonl")
                if s["task"] == proposal["task"] and s["model"] == proposal["model"] and s["patch_id"] is None]
    if not baseline:
        raise ValueError(f"no baseline summary for {proposal['task']} / {proposal['model']}")
    cfg = rn.RunConfig.from_dict({
        "run_id": f"{base_cfg['run_id']}--{proposal['proposal_id']}", "suite": base_cfg["suite"],
        "models": [proposal["model"]], "n_trials": n_trials, "tasks": [proposal["task"]], "max_rounds": 1,
        "patch_id": proposal["proposal_id"], "patch": proposal["patch"], "spend_cap_usd": spend_cap_usd})
    alt_dir = run_dir / "ideation" / proposal["proposal_id"]
    status = rn.Runner(cfg, alt_dir, executor).run()
    alt = [s for s in rn.read_rows(alt_dir / "summary.jsonl") if s["patch_id"] == proposal["proposal_id"]]
    verdict = decide(baseline[0], alt[0] if alt else {}, n=n_trials)
    row = {"schema": RESULT_SCHEMA, "proposal_id": proposal["proposal_id"], "parent_trial_id": proposal["parent_trial_id"],
           "task": proposal["task"], "model": proposal["model"], "credit_method": proposal["credit_method"],
           "baseline_passes": baseline[0]["passes"], "baseline_completed": baseline[0]["completed"],
           "alt_passes": alt[0]["passes"] if alt else None, "alt_completed": alt[0]["completed"] if alt else 0,
           "alt_spend_usd": alt[0]["spend_usd"] if alt else 0.0, "run_state": status["state"],
           "alt_run_dir": f"ideation/{proposal['proposal_id']}", **verdict}
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
