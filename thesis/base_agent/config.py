"""Load, resolve and hash base-agent configs.

Two files define a run:

* ``configs/fixed.toml``: the fixed and infra rows (section 2 of the brief),
  pinned once for every config. Fully fixed slots (M4, M12, M13) are defined
  only here.
* ``configs/<name>.toml``: one config per harness (plus ``base``). It picks an
  implementation for every other slot and cites the sheet for each
  swappable row.

``resolve(cfg, fixed, arm)`` merges them. In the ``swap`` arm every fixed row
is applied. In the ``parity`` arm a row marked ``parity = "harness"`` keeps
the harness's own value (the brief: "harness-specific value only reproduced
for parity"); rows marked ``enforce`` apply in both arms.

``version_record`` is logged on every result row. ``base_agent_version``
changes whenever framework code, a prompt asset, the fixed rows, the config,
or the arm changes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

from thesis.base_agent import modules
from thesis.base_agent.slots import ROW_BY_NUMBER, SLOTS, fully_fixed_slots, non_swappable_rows, swappable_rows

PKG = Path(__file__).resolve().parent
CONFIG_DIR = PKG / "configs"
FIXED_PATH = CONFIG_DIR / "fixed.toml"
ARMS = ("swap", "parity")
SHEET_COLUMNS = {"pi": "pi_src", "opencode": "opencode_src", "hermes": "hermes_src",
                 "zcode": "zcode_src", "codex": "codex_src"}


class ConfigError(ValueError):
    pass


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_toml(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_fixed(path: Path = FIXED_PATH) -> dict:
    fixed = load_toml(path)
    validate_fixed(fixed)
    return fixed


def load_config(name_or_path: str) -> dict:
    p = Path(name_or_path)
    if not p.suffix:
        p = CONFIG_DIR / f"{name_or_path}.toml"
    cfg = load_toml(p)
    cfg.setdefault("name", p.stem)
    return cfg


def validate_fixed(fixed: dict) -> None:
    rows = {int(k): v for k, v in (fixed.get("rows") or {}).items()}
    expected = {r.row for r in non_swappable_rows()}
    if set(rows) != expected:
        raise ConfigError(f"fixed.toml rows {sorted(set(rows) ^ expected)} missing or not fixed/infra")
    for n, spec in rows.items():
        row = ROW_BY_NUMBER[n]
        if not spec.get("value"):
            raise ConfigError(f"fixed row {n} has no value")
        if spec.get("slot", row.slot) != row.slot:
            raise ConfigError(f"fixed row {n} slot {spec.get('slot')} != {row.slot}")
        if spec.get("parity", "enforce") not in ("enforce", "harness"):
            raise ConfigError(f"fixed row {n}: parity must be enforce|harness")
        if spec.get("status", "pinned") not in ("pinned", "provisional"):
            raise ConfigError(f"fixed row {n}: status must be pinned|provisional")
        if row.status == "infra" and ({"set", "drop_tools"} & set(spec)):
            raise ConfigError(f"infra row {n} cannot change a module")
    slots = fixed.get("slots") or {}
    if set(slots) != set(fully_fixed_slots()):
        raise ConfigError(f"fixed.toml [slots] must define exactly {fully_fixed_slots()}")
    for slot, spec in slots.items():
        if "impl" not in spec:
            raise ConfigError(f"fixed slot {slot} has no impl")


def _rows(cfg: dict) -> dict[int, dict]:
    return {int(k): v for k, v in (cfg.get("rows") or {}).items()}


def validate_config(cfg: dict) -> None:
    mods = cfg.get("modules") or {}
    want = set(SLOTS) - set(fully_fixed_slots())
    if set(mods) != want:
        extra, missing = set(mods) - want, want - set(mods)
        raise ConfigError(f"{cfg.get('name')}: modules must set {sorted(want)}; "
                          f"extra {sorted(extra)} (fixed slots go in fixed.toml), missing {sorted(missing)}")
    for slot, spec in mods.items():
        if "impl" not in spec:
            raise ConfigError(f"{cfg.get('name')}: {slot} has no impl")
    for slot in cfg.get("parity") or {}:
        if slot not in fully_fixed_slots():
            raise ConfigError(f"{cfg.get('name')}: [parity.{slot}] only applies to fixed slots")
    harness = cfg.get("harness", "base")
    if harness != "base":
        if not cfg.get("harness_pin"):
            raise ConfigError(f"{cfg['name']}: harness config needs harness_pin")
        rows = _rows(cfg)
        column = SHEET_COLUMNS.get(harness)
        for r in swappable_rows():
            c = rows.get(r.row)
            if not c or not c.get("value") or "source" not in c:
                raise ConfigError(f"{cfg['name']}: row {r.row} ({r.feature}) needs value and source citation")
            if c.get("sheet_column", column) != column:
                raise ConfigError(f"{cfg['name']}: row {r.row} cites {c.get('sheet_column')}, expected {column}")


def resolve(cfg: dict, fixed: dict, arm: str) -> dict:
    if arm not in ARMS:
        raise ConfigError(f"arm must be one of {ARMS}")
    validate_config(cfg)
    modules.load_harness_modules()
    mods = copy.deepcopy(cfg["modules"])
    for spec in mods.values():
        spec.setdefault("params", {})
    applied, harness_kept = [], []
    for slot, spec in fixed["slots"].items():
        if arm == "parity" and spec.get("parity") == "harness" and slot in (cfg.get("parity") or {}):
            mods[slot] = copy.deepcopy(cfg["parity"][slot])
            mods[slot].setdefault("params", {})
            harness_kept.append(slot)
        else:
            mods[slot] = {"impl": spec["impl"], "params": copy.deepcopy(spec.get("params") or {})}
    for n, spec in sorted(_rows(fixed).items()):
        if not ({"set", "drop_tools"} & set(spec)):
            continue
        if arm == "parity" and spec.get("parity") == "harness":
            harness_kept.append(n)
            continue
        params = mods[spec["slot"]]["params"]
        params.update(copy.deepcopy(spec.get("set") or {}))
        if spec.get("drop_tools"):
            params["drop_tools"] = sorted(set(params.get("drop_tools") or []) | set(spec["drop_tools"]))
        applied.append(n)
    for slot, spec in mods.items():
        try:
            modules.build(slot, spec["impl"], spec["params"])
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{cfg.get('name')}: {slot}:{spec['impl']}: {exc}") from exc
    return {"name": cfg["name"], "harness": cfg.get("harness", "base"),
            "harness_pin": cfg.get("harness_pin", ""), "arm": arm,
            "modules": dict(sorted(mods.items(), key=lambda kv: int(kv[0][1:]))),
            "fixed_rows_applied": applied, "harness_values_kept": [str(x) for x in harness_kept]}


def fixed_projection(resolved: dict, fixed: dict) -> dict:
    """Every value the arm holds fixed, read back from the resolved config.

    It must be identical across all configs in the same arm, and a test diffs
    it. Rows and slots that the parity arm leaves to the harness
    (``parity = "harness"``) are left out of the parity projection. Infra rows
    contribute their pinned text.
    """
    kept = set(resolved["harness_values_kept"])
    mods = resolved["modules"]
    out: dict = {}
    for slot in sorted(fixed["slots"]):
        if slot not in kept:
            out[slot] = mods[slot]
    for n, spec in sorted(_rows(fixed).items()):
        if str(n) in kept:
            continue
        entry: dict = {"value": spec["value"]}
        slot = spec.get("slot")
        if spec.get("set"):
            entry["set"] = {k: mods[slot]["params"].get(k) for k in sorted(spec["set"])}
        if spec.get("drop_tools"):
            m2 = mods["M2"]["params"]
            entry["still_exposed"] = sorted(t for t in m2.get("tools", [])
                                            if t in spec["drop_tools"] and t not in (m2.get("drop_tools") or []))
        out[f"row{n}"] = entry
    return out


def framework_files() -> list[Path]:
    """Code and prompt assets; configs are hashed separately."""
    out = []
    for p in sorted(PKG.rglob("*")):
        rel = p.relative_to(PKG)
        if p.is_file() and rel.parts[0] != "configs" and "__pycache__" not in rel.parts and p.suffix != ".pyc" \
                and p.name != "README.md":
            out.append(p)
    return out


def framework_hash() -> str:
    return sha256(canonical({str(p.relative_to(PKG)): sha256(p.read_bytes()) for p in framework_files()}))


def _git_sha() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PKG, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def version_record(cfg: dict, fixed: dict, resolved: dict) -> dict:
    fw = framework_hash()
    resolved_hash = sha256(canonical(resolved))
    provisional = sorted([int(n) for n, s in (fixed.get("rows") or {}).items() if s.get("status") == "provisional"]
                         + [ROW_BY_NUMBER_FOR_SLOT[s] for s, v in fixed["slots"].items() if v.get("status") == "provisional"])
    return {
        "base_agent_version": sha256(canonical({"framework": fw, "resolved": resolved_hash}))[:16],
        "framework_hash": fw,
        "framework_git_sha": _git_sha(),
        "config_name": resolved["name"],
        "config_hash": sha256(canonical(cfg)),
        "fixed_hash": sha256(canonical(fixed)),
        "resolved_hash": resolved_hash,
        "fixed_rows_hash": sha256(canonical(fixed_projection(resolved, fixed))),
        "arm": resolved["arm"],
        "harness": resolved["harness"],
        "harness_pin": resolved["harness_pin"],
        "harness_values_kept": resolved["harness_values_kept"],
        "provisional_fixed_rows": sorted(set(provisional)),
    }


# First sheet row of each fully fixed slot, for reporting provisional slots by row.
ROW_BY_NUMBER_FOR_SLOT = {s: min(r.row for r in ROW_BY_NUMBER.values() if r.slot == s) for s in fully_fixed_slots()}
