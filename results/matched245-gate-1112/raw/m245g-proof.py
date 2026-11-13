#!/usr/bin/env python3
"""Offline-derived proof fields for the OpenCode cells (the smoke cell.py passes no anthropic_sdk pin, so run_cell never
arms the module hook or writes load_proof). Pin = bundled package.json of the OpenCode build (pin_source=bundled_package_json);
loaded version = User-Agent ai-sdk/anthropic/<ver> suffix seen live by the proxy (cache-miss header logs) and the binary's
compiled-in version; verdict = obench.load_proof.judge_load_proof. limit.context = comparison_config() as the cell built it."""
import json, os, re, sys, glob, inspect
from pathlib import Path
REPO = os.path.expanduser("~/ob-m245g"); sys.path.insert(0, REPO); sys.path.insert(0, f"{REPO}/data/opencode-harness-smoke")
from thesis.ab import sdk_pin
from obench import load_proof
B = os.path.expanduser("~/h2/matched245-gate-1112"); SHA = os.environ.get("OPENCODE_SHA", "<REDACTED_HEX>")
out = {"opencode_sha": SHA}
print("bundled_anthropic_pin sig", inspect.signature(sdk_pin.bundled_anthropic_pin))
for root in [os.path.expanduser("~/h1/opencode-src"), os.path.expanduser("~/h1/opencode-src/repo"), os.path.expanduser("~/h1/opencode-src/mirror")]:
    if os.path.exists(root):
        try: r = sdk_pin.bundled_anthropic_pin(Path(root), SHA); print("root", root, "->", r); out.setdefault("bundled_pin_tries", []).append([root, list(r)])
        except Exception as e: print("root", root, "err", e)
pin = next((t[1][0] for t in out.get("bundled_pin_tries", []) if t[1][0]), None); out["pin"] = pin; out["pin_source"] = sdk_pin.BUNDLED_PIN_SOURCE if pin else None
try:
    import obench.provider_embedded as pe
    exe = os.path.expanduser(f"~/h1/opencode-src/bin/{SHA}/opencode"); out["embedded_version"] = pe.embedded_version(exe)
except Exception as e: out["embedded_version_error"] = repr(e)
import importlib.util
s = importlib.util.spec_from_file_location("c", f"{REPO}/data/opencode-harness-smoke/cell.py"); cell = importlib.util.module_from_spec(s); s.loader.exec_module(cell)
os.environ["OBENCH_MATCHED_CONFIG"] = "1"
out["cells"] = {}
for d in sorted(glob.glob(f"{B}/cells/*-opencode-*")):
    m = "claude-opus-5-5" if "opus" in d else "claude-sonnet-5-5"
    uas = set()
    for f in glob.glob(f"{d}/opencode/proxy-ledger/*.cache-miss-headers.jsonl"):
        for l in open(f):
            uas.update(v for k, v in (json.loads(l).get("request_headers") or {}).items() if k.lower() == "user-agent")
    vers = sorted({mm for ua in uas if ua for mm in re.findall(r"ai-sdk/anthropic/([0-9][\w.\-]*)", ua)})
    ua_version = vers[0] if len(vers) == 1 else ("mixed:" + ",".join(vers) if vers else "")
    cfg = cell.comparison_config("http://127.0.0.1:1/c/x/v1", m)
    prov = (cfg.get("provider") or {}); limits = {k: ((v.get("models") or {}).get(m) or {}).get("limit") for k, v in prov.items() if isinstance(v, dict)}
    out["cells"][os.path.basename(d)] = {"user_agents": sorted(u for u in uas if u), "ua_anthropic_version": ua_version,
        "verdict": load_proof.judge_load_proof(pin=pin or "", ua_version=ua_version, embedded_version=out.get("embedded_version") or "", compiled=True),
        "config_model": cfg.get("model"), "config_small_model": cfg.get("small_model"), "config_limits": limits,
        "config_has_thinking_option": "thinking" in json.dumps(cfg)}
json.dump(out, open(f"{B}/opencode-proof.json", "w"), indent=1); print(json.dumps(out, indent=1)[:4000])
