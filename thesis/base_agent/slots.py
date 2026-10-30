"""The 13 module slots and the 34 sheet rows they cover.

Source: briefs/stage4-prereg-base-agent.md section 2, which maps every row of
prereg/harness-components-2026-10-24.csv (the harness comparison sheet) to a
module. ``status`` is the brief's classification:

* ``swappable``: a module slot varied in Stage 4.
* ``fixed``: held constant across swap configs. The harness's own value is
  reproduced only in the parity arm.
* ``infra``: outside the agent (runner, proxy, container). Recorded, never
  varied, and the base agent has no knob for it.
"""
from __future__ import annotations

from dataclasses import dataclass

SLOTS = {
    "M1": "PromptAssembler",
    "M2": "ToolRegistry",
    "M3": "CachePolicy",
    "M4": "SamplingPolicy",
    "M5": "SideCalls",
    "M6": "ContextManager",
    "M7": "Editor",
    "M8": "Executor",
    "M9": "Planner",
    "M10": "Delegation",
    "M11": "LoopController",
    "M12": "RetryPolicy",
    "M13": "Permissions",
}

STATUSES = ("swappable", "fixed", "infra")


@dataclass(frozen=True)
class Row:
    row: int
    layer: str
    feature: str  # exact `feature` cell in harness-components-2026-10-24.csv
    slot: str | None  # M1..M13, or None for infra rows
    status: str


ROWS: tuple[Row, ...] = (
    Row(1, "model/prompt", "System prompt structure + length", "M1", "swappable"),
    Row(2, "model/prompt", "Per-task prompt variation", "M1", "swappable"),
    Row(3, "model/prompt", "Tool count (built-in default)", "M2", "swappable"),
    Row(4, "model/prompt", "Tool schema size", "M2", "swappable"),
    Row(5, "model/prompt", "Tool descriptor format", "M2", "swappable"),
    Row(6, "model/prompt", "Provider routing / Vertex", None, "infra"),
    Row(7, "model/prompt", "Custom API base URL (proxy token counting)", None, "infra"),
    Row(8, "model/prompt", "Prompt caching breakpoints", "M3", "swappable"),
    Row(9, "model/prompt", "Temperature / reasoning", "M4", "fixed"),
    Row(10, "model/prompt", "Title / side model calls", "M5", "swappable"),
    Row(11, "context", "Code search", "M2", "swappable"),
    Row(12, "context", "File read mode", "M2", "swappable"),
    Row(13, "context", "History compaction", "M6", "swappable"),
    Row(14, "context", "Memory files", "M1", "fixed"),
    Row(15, "acting", "Edit format", "M7", "swappable"),
    Row(16, "acting", "Shell exec / timeout", "M8", "swappable"),
    Row(17, "acting", "Output truncation", "M8", "swappable"),
    Row(18, "acting", "Sandbox", None, "infra"),
    Row(19, "acting", "Web / fetch", "M2", "fixed"),
    Row(20, "acting", "MCP / plugins", "M2", "fixed"),
    Row(21, "control loop", "Planning / todo", "M9", "swappable"),
    Row(22, "control loop", "Subagents and context", "M10", "swappable"),
    Row(23, "control loop", "Stop rules / step caps", "M11", "fixed"),
    Row(24, "control loop", "Retries", "M12", "fixed"),
    Row(25, "control loop", "Error recovery / self-verify", "M11", "swappable"),
    Row(26, "safety", "Permission model", "M13", "fixed"),
    Row(27, "safety", "Headless behaviour when it would ask", "M13", "fixed"),
    Row(28, "safety", "Path guards", "M13", "fixed"),
    Row(29, "safety", "Destructive-command handling", "M13", "fixed"),
    Row(30, "safety", "Secret redaction", None, "infra"),
    Row(31, "safety", "Project trust", None, "infra"),
    Row(32, "ops", "Headless CLI mode", None, "infra"),
    Row(33, "ops", "Token usage logging", None, "infra"),
    Row(34, "ops", "License / source", None, "infra"),
)

ROW_BY_NUMBER = {r.row: r for r in ROWS}


def rows_for(slot: str) -> list[Row]:
    return [r for r in ROWS if r.slot == slot]


def swappable_rows() -> list[Row]:
    return [r for r in ROWS if r.status == "swappable"]


def non_swappable_rows() -> list[Row]:
    return [r for r in ROWS if r.status != "swappable"]


def fully_fixed_slots() -> list[str]:
    """Slots whose every row is fixed. A swap config may not choose them."""
    return [s for s in SLOTS if rows_for(s) and all(r.status == "fixed" for r in rows_for(s))]
