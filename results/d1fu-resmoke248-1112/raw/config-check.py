#!/usr/bin/env python3
"""Dump the assessed + bound OpenCode config at this runner for both SHAs."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/ob")

from thesis.ab.compat import assess
from thesis.ab.run_ab import SONNET_CONTEXT_LIMIT, bind_opencode_model, _decorate_toolchain
from thesis.ab.sdk_pin import BUNDLED_PIN_SOURCE, bundled_anthropic_pin

CACHE = Path("/h1/opencode-src")
SHAS = [
    ("without", "c436fc69eb039523795555f0ec88d32f20ea3292"),
    ("with", "d7af1f17056dd4c216b9aa62f03491c6f8fbeeb0"),
]


def models_limits(config: dict) -> dict:
    out = {}
    providers = (config or {}).get("provider") or {}
    if not isinstance(providers, dict):
        return {"_raw_keys": sorted((config or {}).keys()), "_note": "no provider map"}
    for pname, provider in providers.items():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models") or {}
        if not isinstance(models, dict):
            continue
        for mid, entry in models.items():
            if isinstance(entry, dict):
                out[f"{pname}/{mid}"] = {
                    "name": entry.get("name"),
                    "limit": entry.get("limit"),
                }
    return out


def main() -> int:
    print(f"runner {os.environ.get('OBENCH_RUNNER_COMMIT') or 'unknown'}")
    print(f"SONNET_CONTEXT_LIMIT={SONNET_CONTEXT_LIMIT}")
    print(f"BUNDLED_PIN_SOURCE={BUNDLED_PIN_SOURCE}")
    report = {}
    for side, sha in SHAS:
        binary = CACHE / "bin" / sha / "opencode"
        checkout = CACHE / "worktrees" / sha
        pin, pin_err, bundled = bundled_anthropic_pin(checkout, sha)
        section = {
            "sha": sha,
            "binary_exists": binary.is_file(),
            "bundled_anthropic_pin": pin,
            "bundled_pin_error": pin_err,
            "bundled": bundled,
        }
        print(f"\n== {side} {sha} ==")
        print(f"bundled_anthropic_pin pin={pin} bundled={bundled} err={pin_err}")
        if not binary.is_file():
            print("MISSING binary")
            report[side] = section
            continue
        assessment = assess(str(binary), route="proxy", proxy_url="http://127.0.0.1:9")
        section["assessment_status"] = assessment.status
        section["assessment_reason"] = assessment.reason
        section["assessment_models"] = models_limits(assessment.config or {})
        print(f"assess status={assessment.status} reason={assessment.reason}")
        print("assessed models:", json.dumps(section["assessment_models"], sort_keys=True))
        bound_config, bound_proxy = bind_opencode_model(
            assessment.config, assessment.proxy, "claude-sonnet-5-5"
        )
        section["bound_models"] = models_limits(bound_config)
        section["bound_model_ref"] = (
            (bound_proxy or {}).get("model_ref") if isinstance(bound_proxy, dict) else None
        )
        print("bound models:", json.dumps(section["bound_models"], sort_keys=True))
        print("bound model_ref:", section["bound_model_ref"])
        prepared = {
            "ok": True,
            "binary": str(binary),
            "config": assessment.config,
            "permission_config": assessment.permission_config,
            "harness": "opencode",
            "vertex": assessment.vertex,
            "proxy": assessment.proxy,
        }
        decorated, decorate_err = _decorate_toolchain(prepared, CACHE, sha, "sst/opencode")
        proxy = decorated.get("proxy") if isinstance(decorated, dict) else None
        section["decorate_error"] = decorate_err
        section["pin_source"] = (proxy or {}).get("pin_source") if isinstance(proxy, dict) else None
        section["anthropic_sdk"] = (proxy or {}).get("anthropic_sdk") if isinstance(proxy, dict) else None
        section["toolchain"] = (decorated or {}).get("toolchain") if isinstance(decorated, dict) else None
        print(
            f"decorate err={decorate_err} pin_source={section['pin_source']} "
            f"anthropic_sdk={section['anthropic_sdk']}"
        )
        print("toolchain:", json.dumps(section["toolchain"], sort_keys=True))
        sonnet_contexts = []
        for key, entry in (section["bound_models"] or {}).items():
            if "claude-sonnet-5-5" in key and isinstance(entry, dict) and isinstance(entry.get("limit"), dict):
                sonnet_contexts.append((key, entry["limit"].get("context")))
        section["sonnet_contexts"] = sonnet_contexts
        section["context_ok"] = bool(sonnet_contexts) and all(c == 200000 for _, c in sonnet_contexts)
        print(f"sonnet_contexts={sonnet_contexts} context_ok={section['context_ok']}")
        report[side] = section
    Path("/o/config-check.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
