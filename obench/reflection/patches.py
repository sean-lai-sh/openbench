"""Ideation patches: prompt and tool-metadata changes only (SEA-110).

A patch is ``{"schema": PATCH_SCHEMA, "ops": [...]}`` with ops from a
closed set. Each op edits the **system prompt** or **tool-call metadata**
(a tool's description, or one parameter's description) on the request the
harness sends. The recording proxy applies it to every model request of
an alternative's trials (``apply_patch``), per wire format.

Anything else is out of surface and rejected by ``validate_patch``:
- agent code, files and diffs;
- task instructions or checkers;
- model, provider or route;
- sampling parameters and other hyperparameters;
- tool *schemas* beyond descriptions (types, required fields), message
  history.

The op set is closed, so a patch can't express a code change.
"""

from __future__ import annotations

import copy
import hashlib
import json

PATCH_SCHEMA = "openbench.reflection.patch/v1"
OPS = {
    "system_append": {"text"},
    "system_replace": {"find", "replace"},
    "tool_description": {"tool", "description"},
    "tool_param_description": {"tool", "param", "description"},
}
MAX_TEXT = 8000
MAX_OPS = 8


class PatchError(ValueError):
    pass


def validate_patch(patch) -> list[str]:
    """Reasons the patch is out of surface or malformed; empty when valid."""
    if not isinstance(patch, dict):
        return ["patch is not an object"]
    reasons = []
    extra = set(patch) - {"schema", "ops"}
    if extra:
        reasons.append(f"keys outside the patch surface: {sorted(extra)}")
    if patch.get("schema") != PATCH_SCHEMA:
        reasons.append(f"schema must be {PATCH_SCHEMA}")
    ops = patch.get("ops")
    if not isinstance(ops, list) or not ops:
        return reasons + ["ops must be a non-empty list"]
    if len(ops) > MAX_OPS:
        reasons.append(f"at most {MAX_OPS} ops")
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or op.get("op") not in OPS:
            reasons.append(f"op {i}: {op.get('op') if isinstance(op, dict) else op!r} is not one of {sorted(OPS)}")
            continue
        fields = set(op) - {"op"}
        if fields != OPS[op["op"]]:
            reasons.append(f"op {i} ({op['op']}): fields {sorted(fields)}, expected {sorted(OPS[op['op']])}")
            continue
        for key in fields:
            value = op[key]
            if not isinstance(value, str) or not value.strip() and key != "replace":
                reasons.append(f"op {i}: {key} must be a non-empty string")
            elif len(value) > MAX_TEXT:
                reasons.append(f"op {i}: {key} longer than {MAX_TEXT} characters")
    return reasons


def patch_id(patch: dict) -> str:
    return "p" + hashlib.sha256(json.dumps(patch, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def _apply_text(text: str, op: dict) -> tuple[str, bool]:
    if op["op"] == "system_append":
        return (text + ("\n\n" if text else "") + op["text"]), True
    if op["find"] in text:
        return text.replace(op["find"], op["replace"]), True
    return text, False


def _system_anthropic(body: dict, op: dict) -> bool:
    system = body.get("system")
    if system is None or isinstance(system, str):
        body["system"], hit = _apply_text(system or "", op)
        return hit
    if op["op"] == "system_append":
        system.append({"type": "text", "text": op["text"]})
        return True
    hit = False
    for block in system:
        if isinstance(block, dict) and isinstance(block.get("text"), str) and op["find"] in block["text"]:
            block["text"], hit = block["text"].replace(op["find"], op["replace"]), True
    return hit


def _system_openai(body: dict, op: dict) -> bool:
    messages = body.setdefault("messages", [])
    first = messages[0] if messages and messages[0].get("role") in ("system", "developer") else None
    if first is None:
        if op["op"] != "system_append":
            return False
        messages.insert(0, {"role": "system", "content": op["text"]})
        return True
    if isinstance(first.get("content"), str):
        first["content"], hit = _apply_text(first["content"], op)
        return hit
    return False


def _system_gemini(body: dict, op: dict) -> bool:
    instr = body.setdefault("systemInstruction", {"parts": []})
    parts = instr.setdefault("parts", [])
    if op["op"] == "system_append":
        parts.append({"text": op["text"]})
        return True
    hit = False
    for part in parts:
        if isinstance(part.get("text"), str) and op["find"] in part["text"]:
            part["text"], hit = part["text"].replace(op["find"], op["replace"]), True
    return hit


def _tools(body: dict, wire: str):
    """(name, description holder, parameter-properties dict) per tool."""
    if wire == "anthropic":
        for t in body.get("tools") or []:
            yield t.get("name"), t, ((t.get("input_schema") or {}).get("properties") or {})
    elif wire == "openai_chat":
        for t in body.get("tools") or []:
            fn = t.get("function") or {}
            yield fn.get("name"), fn, ((fn.get("parameters") or {}).get("properties") or {})
    else:
        for group in body.get("tools") or []:
            for fn in group.get("functionDeclarations") or []:
                yield fn.get("name"), fn, ((fn.get("parameters") or {}).get("properties") or {})


def apply_patch(wire: str, body: dict, patch: dict) -> tuple[dict, list[dict]]:
    """``(patched body, per-op application log)``. The input body is not
    modified. An op that finds nothing to change is logged ``applied: false``."""
    reasons = validate_patch(patch)
    if reasons:
        raise PatchError("; ".join(reasons))
    out = copy.deepcopy(body)
    log = []
    system = {"anthropic": _system_anthropic, "openai_chat": _system_openai, "gemini": _system_gemini}[wire]
    for op in patch["ops"]:
        if op["op"] in ("system_append", "system_replace"):
            hit = system(out, op)
        else:
            hit = False
            for name, holder, props in _tools(out, wire):
                if name != op["tool"]:
                    continue
                if op["op"] == "tool_description":
                    holder["description"], hit = op["description"], True
                elif op["param"] in props and isinstance(props[op["param"]], dict):
                    props[op["param"]]["description"], hit = op["description"], True
        log.append({"op": op["op"], "applied": hit})
    return out, log
