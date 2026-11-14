"""Credit assignment Method B: System 1 weights over the first failure + K earlier steps (SEA-109).

For every failed trial (the same rows Method A reads), Method B:

1. finds the first failing step ``f`` with the shared locator
   (``credit_locator.first_failure``, so A and B agree on ``f``);
2. asks a System 1 model to label each of the ``K`` steps before ``f`` as
   ``correct`` or ``near_error`` (it contributed to the failure);
3. assigns weights: ``CORRECT_WEIGHT`` to every step before the window and to
   window steps labelled correct, ``NEAR_ERROR_WEIGHT`` to window steps
   labelled near-error, and ``PAST_CUTOFF_WEIGHT`` to ``f`` and everything
   after it (``CUTOFF_RULE``).

It writes its own table, ``credit_b.jsonl``. It never touches
``trials.jsonl`` or ``credit_a.jsonl``.

**Provisional, open (CREDIT_ASSIGNMENT.md):** ``K = 2`` and
``NEAR_ERROR_WEIGHT = 0.5``. The System 1 model defaults to Gemini Flash
(``gemini-3.8-flash`` on Vertex, location ``global``) until Sean confirms
whether "Jev" is a specific endpoint. All of these are config: change
``MethodBConfig`` or pass ``--config``.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from obench.reflection.credit_locator import LOCATOR_RULE_VERSION, failed_trials, first_failure, read_trace

METHOD_B_SCHEMA = "openbench.reflection.credit_b/v1"
PROMPT_VERSION = "B1"
TABLE = "credit_b.jsonl"
LABELS = ("correct", "near_error")

# Provisional defaults (open items; see CREDIT_ASSIGNMENT.md).
K = 2
NEAR_ERROR_WEIGHT = 0.5
CORRECT_WEIGHT = 1.0
PAST_CUTOFF_WEIGHT = 0.0
CUTOFF_RULE = "first_failing_step_onward"   # the failing step and every later step get PAST_CUTOFF_WEIGHT
SYSTEM1_MODEL = "gemini-3.8-flash"          # "Jev" unconfirmed; Gemini Flash is the default
SYSTEM1_LOCATION = "global"
SYSTEM1_THINKING = {"thinkingLevel": "LOW"}  # set explicitly on every judge request
_RESULT_CHARS = 1500


@dataclass(frozen=True)
class MethodBConfig:
    k: int = K
    near_error_weight: float = NEAR_ERROR_WEIGHT
    correct_weight: float = CORRECT_WEIGHT
    past_cutoff_weight: float = PAST_CUTOFF_WEIGHT
    cutoff_rule: str = CUTOFF_RULE
    system1_model: str = SYSTEM1_MODEL
    system1_location: str = SYSTEM1_LOCATION
    system1_thinking: dict = field(default_factory=lambda: dict(SYSTEM1_THINKING))

    @classmethod
    def from_dict(cls, raw: dict) -> "MethodBConfig":
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown Method B config keys: {sorted(unknown)}")
        cfg = cls(**raw)
        if cfg.k < 0 or not 0.0 <= cfg.near_error_weight <= 1.0 or cfg.cutoff_rule != CUTOFF_RULE:
            raise ValueError("k must be >= 0, near_error_weight in [0, 1], cutoff_rule first_failing_step_onward")
        if not cfg.system1_thinking:
            raise ValueError("system1_thinking must be set explicitly")
        return cfg


class System1(Protocol):
    model_id: str

    def judge(self, prompt: str) -> tuple[str, dict | None]:
        """Raw text of the model's JSON answer, and its usage object."""


def _step_digest(step: dict) -> dict:
    calls = [{"tool": c.get("name"), "arguments": c.get("arguments"),
              "result": (c.get("result") if isinstance(c.get("result"), str) else json.dumps(c.get("result")))[:_RESULT_CHARS],
              "status": c.get("status")} for c in step.get("tool_calls") or []]
    return {"step": step.get("step"), "assistant_text": (step.get("assistant_text") or "")[:_RESULT_CHARS],
            "tool_calls": calls}


def build_prompt(task: str, failing: dict, window: list[dict], signal: str) -> str:
    """Prompt version ``PROMPT_VERSION``. Deterministic for the same inputs."""
    payload = {"task": task, "first_failing_step": _step_digest(failing), "failure_signal": signal,
               "earlier_steps": [_step_digest(s) for s in window]}
    return (
        "You are auditing a coding agent's failed attempt at a task. The first failing step is given, "
        "with the steps just before it. For EACH earlier step, decide whether it was correct, or whether it "
        "contributed to the failure (near_error). Judge only the steps listed; do not judge the failing step.\n"
        "Answer with JSON only: {\"labels\": [{\"step\": <int>, \"label\": \"correct\" | \"near_error\", "
        "\"reason\": <one sentence>}]}, one entry per earlier step.\n\n"
        + json.dumps(payload, sort_keys=True, indent=1)
    )


def parse_labels(raw: str, window_steps: list[int]) -> dict[int, str]:
    """``{step: label}`` for exactly the window steps, or ValueError."""
    doc = json.loads(raw)
    labels = {}
    for item in doc.get("labels") or []:
        if item.get("label") not in LABELS:
            raise ValueError(f"label {item.get('label')!r} is not one of {LABELS}")
        labels[int(item["step"])] = item["label"]
    if sorted(labels) != sorted(window_steps):
        raise ValueError(f"judge labelled steps {sorted(labels)}, expected {sorted(window_steps)}")
    return labels


def weights(steps: list[int], failing_step: int, labels: dict[int, str], cfg: MethodBConfig) -> list[dict]:
    """The weight vector, one entry per trace step."""
    window = set(range(failing_step - cfg.k, failing_step))
    out = []
    for step in sorted(steps):
        if step >= failing_step:
            weight, why = cfg.past_cutoff_weight, "past_cutoff"
        elif step in window and labels.get(step) == "near_error":
            weight, why = cfg.near_error_weight, "near_error"
        else:
            weight, why = cfg.correct_weight, "correct" if step in window else "before_window"
        out.append({"step": step, "weight": weight, "why": why})
    return out


def method_b_row(trial: dict, steps: list[dict], judge: System1, cfg: MethodBConfig) -> dict:
    found = first_failure(steps)
    row = {"schema": METHOD_B_SCHEMA, "prompt_version": PROMPT_VERSION, "locator_rule_version": LOCATOR_RULE_VERSION,
           "run_id": trial.get("run_id"), "trial_id": trial["trial_id"], "task": trial["task"], "model": trial["model"],
           "patch_id": trial.get("patch_id"), "system1_model": judge.model_id, "system1_thinking": cfg.system1_thinking,
           "k": cfg.k, "near_error_weight": cfg.near_error_weight, "correct_weight": cfg.correct_weight,
           "past_cutoff_weight": cfg.past_cutoff_weight, "cutoff_rule": cfg.cutoff_rule,
           "first_failing_step": found.step, "signal": found.signal, "window": [], "labels": None, "weights": None,
           "raw_judge_output": None, "judge_usage": None, "judge_error": None, "trace": trial.get("trace")}
    if found.step is None:
        row["judge_error"] = "empty_trace"
        return row
    by_step = {s["step"]: s for s in steps}
    window = [n for n in range(found.step - cfg.k, found.step) if n in by_step]
    row["window"] = window
    labels: dict[int, str] = {}
    if window:
        prompt = build_prompt(trial["task"], by_step[found.step], [by_step[n] for n in window], found.signal)
        try:
            raw, usage = judge.judge(prompt)
        except Exception as exc:  # recorded, never silently dropped
            row["judge_error"] = f"{type(exc).__name__}: {exc}"
            return row
        row["raw_judge_output"], row["judge_usage"] = raw, usage
        try:
            labels = parse_labels(raw, window)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            row["judge_error"] = f"unparseable judge output: {exc}"
            return row
    row["labels"] = {str(k): v for k, v in sorted(labels.items())}
    row["weights"] = weights(list(by_step), found.step, labels, cfg)
    return row


def run_method_b(run_dir: Path, judge: System1, cfg: MethodBConfig | None = None) -> list[dict]:
    cfg = cfg or MethodBConfig()
    run_dir = Path(run_dir)
    rows = []
    for trial in failed_trials(run_dir):
        steps = read_trace(run_dir / trial["trace"]) if trial.get("trace") else []
        rows.append(method_b_row(trial, steps, judge, cfg))
    tmp = run_dir / (TABLE + ".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, run_dir / TABLE)
    return rows


class VertexGeminiJudge:
    """System 1 on Vertex ``generateContent`` with ADC: temperature 0, a JSON
    response schema, and the thinking setting sent explicitly."""

    def __init__(self, cfg: MethodBConfig, project: str, token: Callable[[], str], opener=urllib.request.urlopen):
        self.model_id, self.cfg, self.project, self.token, self.opener = cfg.system1_model, cfg, project, token, opener

    def request_body(self, prompt: str) -> dict:
        schema = {"type": "OBJECT", "properties": {"labels": {"type": "ARRAY", "items": {
            "type": "OBJECT", "properties": {"step": {"type": "INTEGER"}, "label": {"type": "STRING", "enum": list(LABELS)},
                                             "reason": {"type": "STRING"}}, "required": ["step", "label"]}}},
                  "required": ["labels"]}
        return {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                     "responseSchema": schema, "thinkingConfig": dict(self.cfg.system1_thinking)}}

    def judge(self, prompt: str) -> tuple[str, dict | None]:
        url = (f"https://aiplatform.googleapis.com/v1/projects/{self.project}/locations/{self.cfg.system1_location}"
               f"/publishers/google/models/{self.model_id}:generateContent")
        req = urllib.request.Request(url, data=json.dumps(self.request_body(prompt)).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token()}"})
        with self.opener(req, timeout=120) as resp:
            doc = json.loads(resp.read())
        parts = doc["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return text, doc.get("usageMetadata")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Credit assignment Method B (System 1 weights)")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="MethodBConfig JSON (k, near_error_weight, system1_model, ...)")
    args = parser.parse_args(argv)
    cfg = MethodBConfig.from_dict(json.loads(args.config.read_text())) if args.config else MethodBConfig()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project:
        raise SystemExit("GOOGLE_CLOUD_PROJECT is not set")
    from thesis.ab.vertex_anthropic_proxy import AdcToken

    rows = run_method_b(args.run, VertexGeminiJudge(cfg, project, AdcToken()), cfg)
    print(json.dumps({"rows": len(rows), "table": str(args.run / TABLE), "errors": sum(1 for r in rows if r["judge_error"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
