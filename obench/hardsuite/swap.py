"""Per-model harder-swap rule (SEA-106).

Each model has its own copy of the suite: one slot per planned task. After a
batch of trials, a task *passes* for that model when
``successes / trials >= cutoff`` (``config.pass_cutoff()``; the default
``config.PASS_CUTOFF`` needs 27/30 at N=30). A passing task is swapped, for that model only, for the
*easiest task that is still strictly harder* in the suite's harder pool, so
difficulty climbs one rung at a time. "Harder" means a strictly lower
published frontier rate; ties are not harder, and among equally hard
candidates the lowest id wins. A replacement is never a task the model
already has in a slot or has already retired. Other models keep their
original task until they pass it themselves.

The suite never shrinks: if no eligible harder task is left, ``apply_results``
raises ``PoolExhausted`` and changes nothing; grow the pool and re-run it.

State is a plain JSON-able dict per model::

    {"schema": "openbench.hard-swap/v1", "model": ..., "suite": ..., "pool": ...,
     "slots": [{"slot": 0, "task": "dna-insert", "retired": []}, ...],
     "swaps": [{"slot", "from", "to", "from_rate", "to_rate", "successes", "trials", "cutoff"}, ...]}
"""

from __future__ import annotations

import copy
import math

from obench.hardsuite.config import pass_cutoff
from obench.hardsuite.suite import Suite, Task

SWAP_SCHEMA = "openbench.hard-swap/v1"


class SwapError(ValueError):
    pass


class PoolExhausted(SwapError):
    """No harder replacement is left for a passing task; the suite would shrink."""


def passed(successes: int, trials: int, cutoff: float | None = None) -> bool:
    """``successes / trials >= cutoff``, computed exactly (27 of 30 meets the default)."""
    cutoff = pass_cutoff() if cutoff is None else cutoff
    if isinstance(trials, bool) or not isinstance(trials, int) or trials <= 0:
        raise SwapError(f"trials must be a positive int, got {trials!r}")
    if isinstance(successes, bool) or not isinstance(successes, int) or not 0 <= successes <= trials:
        raise SwapError(f"successes must be an int in [0, {trials}], got {successes!r}")
    return successes >= math.ceil(round(cutoff * trials, 9))


def initial_state(model: str, suite: Suite) -> dict:
    if suite.planned_size != len(suite.tasks):
        raise SwapError(f"suite {suite.name!r} lists {len(suite.tasks)} tasks but plans {suite.planned_size}")
    return {"schema": SWAP_SCHEMA, "model": model, "suite": suite.name, "pool": suite.pool,
            "slots": [{"slot": i, "task": t.id, "retired": []} for i, t in enumerate(suite.tasks)],
            "swaps": []}


def _replacement(current: Task, pool: Suite, taken: set[str]) -> Task | None:
    harder = [t for t in pool.tasks if t.frontier_rate < current.frontier_rate and t.id not in taken]
    if not harder:
        return None
    rung = max(t.frontier_rate for t in harder)
    return min((t for t in harder if t.frontier_rate == rung), key=lambda t: t.id)


def apply_results(state: dict, results: dict[str, tuple[int, int]], suite: Suite, pool: Suite,
                  cutoff: float | None = None) -> tuple[dict, list[dict]]:
    """Swap every task that passed for this model. ``results`` maps a task id
    in the model's current slots to ``(successes, trials)``. Returns the new
    state and the swaps made; ``state`` itself is not modified."""
    if state.get("schema") != SWAP_SCHEMA or state.get("suite") != suite.name:
        raise SwapError(f"state is not a {SWAP_SCHEMA} state for suite {suite.name!r}")
    cutoff = pass_cutoff() if cutoff is None else cutoff
    known = {t.id: t for t in (*suite.tasks, *pool.tasks)}
    new = copy.deepcopy(state)
    current = {slot["task"]: slot for slot in new["slots"]}
    unknown = sorted(set(results) - set(current))
    if unknown:
        raise SwapError(f"results for tasks not in {state['model']}'s slots: {unknown}")
    taken = {s["task"] for s in new["slots"]} | {r for s in new["slots"] for r in s["retired"]}
    swaps = []
    for slot in new["slots"]:
        if slot["task"] not in results:
            continue
        successes, trials = results[slot["task"]]
        if not passed(successes, trials, cutoff):
            continue
        old = known[slot["task"]]
        pick = _replacement(old, pool, taken)
        if pick is None:
            raise PoolExhausted(f"{state['model']}: {old.id} passed ({successes}/{trials} >= {cutoff}) but "
                                f"pool {pool.name!r} has no unused task harder than {old.frontier_rate}")
        taken.add(pick.id)
        slot["retired"].append(old.id)
        slot["task"] = pick.id
        swaps.append({"slot": slot["slot"], "from": old.id, "to": pick.id, "from_rate": old.frontier_rate,
                      "to_rate": pick.frontier_rate, "successes": successes, "trials": trials, "cutoff": cutoff})
    new["swaps"].extend(swaps)
    return new, swaps


def current_tasks(state: dict) -> list[str]:
    return [slot["task"] for slot in state["slots"]]


def pool_capacity(suite: Suite, pool: Suite) -> list[dict]:
    """Per slot: how many pool tasks are harder than its starting task. A
    model can swap a slot that many times at most; ``apply_results`` raises
    ``PoolExhausted`` past that (or sooner, when slots share candidates)."""
    return [{"slot": i, "task": t.id, "harder_in_pool": sum(p.frontier_rate < t.frontier_rate for p in pool.tasks)}
            for i, t in enumerate(suite.tasks)]
