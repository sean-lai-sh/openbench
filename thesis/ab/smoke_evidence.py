"""Four-check evidence for a harness-comparison smoke cell (Codex, Hermes).

Computed from the cell row (``attach_proxy_trace`` already applied) and the
cell's proxy ledger rows:

1. ``1_traced``: every proxy request is traced by the harness
   (``trace_requests`` == ledger requests, ``untraced_requests`` == 0).
2. ``2_cache_read``: ``cache_read`` > 0 on every call from call 2 on.
3. ``3_thinking_sent``: ``thinking_sent`` equals the reference arm's value
   for the same model. OpenCode is the Researcher's thinking reference;
   other arms are listed for context. Server-side thinking tokens (usage
   fields the upstream reports even when no thinking was requested) are
   recorded separately and do not affect the check.
4. ``4_prompt_bytes``: system and tool bytes the proxy forwarded are within
   5% of what the harness itself sent. Byte counts come from the ledger:
   ``cc_identity_stripped.responses`` (Responses translation, Codex) or
   ``cc_identity_stripped.capture`` (raw capture, ``OBENCH_VERTEX_CAPTURE_REQUESTS``).
"""

from __future__ import annotations

import json
from pathlib import Path

REFERENCE_LEDGERS = "results/pi-vs-oc-180-1029/cells/*/{arm}/proxy-ledger/*.jsonl"
REFERENCE_ARMS = ("pi", "opencode")
THINKING_REFERENCE_ARM = "opencode"
BYTE_TOLERANCE = 0.05
_THINKING_KEYS = ("thinking_tokens", "reasoning_tokens", "reasoning_output_tokens")


def reference_thinking(repo: Path, model: str, pattern: str = REFERENCE_LEDGERS) -> dict:
    """``thinking_sent`` values each reference arm recorded for ``model``."""
    found: dict = {}
    for arm in REFERENCE_ARMS:
        values: set = set()
        for path in sorted(Path(repo).glob(pattern.format(arm=arm))):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("upstream_model") == model and row.get("thinking_sent"):
                    values.add(row["thinking_sent"])
        found[arm] = sorted(values)
    return found


def _delta(captured, real):
    if not isinstance(captured, int) or not isinstance(real, int) or real <= 0:
        return None
    return round((captured - real) / real, 4)


def server_thinking_tokens(usage) -> int | None:
    """Thinking/reasoning tokens the upstream reported in ``usage``, or None."""
    if not isinstance(usage, dict):
        return None
    total = None
    for key in _THINKING_KEYS:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total = (total or 0) + value
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        for key in _THINKING_KEYS:
            value = details.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                total = (total or 0) + value
    return total


def _byte_record(row: dict) -> dict | None:
    identity = row.get("cc_identity_stripped") or {}
    rec = identity.get("responses") or {}
    if "responses_raw_system_bytes" in rec:
        return {
            "raw_request_file": rec.get("responses_raw_request_file"),
            "system_bytes": rec.get("responses_system_bytes"),
            "raw_system_bytes": rec.get("responses_raw_system_bytes"),
            "tools_bytes": rec.get("responses_tools_bytes"),
            "raw_tools_bytes": rec.get("responses_raw_tools_bytes"),
        }
    cap = identity.get("capture") or {}
    if "raw_system_bytes" in cap:
        return {
            "raw_request_file": cap.get("raw_request_file"),
            "system_bytes": cap.get("system_bytes"),
            "raw_system_bytes": cap.get("raw_system_bytes"),
            "tools_bytes": cap.get("tools_bytes"),
            "raw_tools_bytes": cap.get("raw_tools_bytes"),
        }
    return None


def _within(delta, raw) -> bool:
    if raw == 0:
        return True  # nothing sent (e.g. a tool-less side call): nothing to differ
    return delta is not None and abs(delta) <= BYTE_TOLERANCE


def smoke_evidence(row: dict, ledger_rows: list, reference: dict | None = None,
                   reference_arm: str = THINKING_REFERENCE_ARM) -> dict:
    rows = [r for r in ledger_rows if isinstance(r, dict) and isinstance(r.get("usage"), dict)]
    calls = len(rows)
    traced = row.get("trace_requests")
    untraced = row.get("untraced_requests")
    cache_reads = [r.get("cache_read") for r in rows]
    sent = sorted({str(r.get("thinking_sent")) for r in rows})
    thinking_tokens = [server_thinking_tokens(r.get("usage")) for r in rows]
    reference = reference or {}
    byte_rows = []
    for r in rows:
        rec = _byte_record(r)
        if rec is None:
            continue
        rec["system_delta"] = _delta(rec["system_bytes"], rec["raw_system_bytes"])
        rec["tools_delta"] = _delta(rec["tools_bytes"], rec["raw_tools_bytes"])
        rec["call_role"] = r.get("call_role")
        byte_rows.append(rec)
    within = bool(byte_rows) and all(
        _within(b["system_delta"], b["raw_system_bytes"]) and _within(b["tools_delta"], b["raw_tools_bytes"])
        for b in byte_rows
    )
    matches = {arm: sent == values for arm, values in reference.items()}
    return {
        "1_traced": {
            "proxy_requests": calls, "trace_requests": traced, "untraced_requests": untraced,
            "pass": calls > 0 and traced == calls and untraced == 0,
        },
        "2_cache_read": {
            "per_call": cache_reads,
            "pass": calls >= 2 and all(isinstance(v, int) and v > 0 for v in cache_reads[1:]),
        },
        "3_thinking_sent": {
            "harness": sent, "reference_arm": reference_arm, "reference": reference,
            "matches": matches,
            "server_thinking_tokens_per_call": thinking_tokens,
            "pass": bool(matches.get(reference_arm)),
        },
        "4_prompt_bytes": {
            "tolerance": BYTE_TOLERANCE, "per_call": byte_rows, "pass": within,
        },
    }
