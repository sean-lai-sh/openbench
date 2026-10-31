"""Which ``@ai-sdk/anthropic`` copy an OpenCode arm actually loaded.

``loaded_anthropic`` (the ``ai-sdk/anthropic/<ver>`` User-Agent suffix) stays
the main proof wherever the request header carries a version. Pins before
2.0.18 send no suffix, and OpenCode v1.15.2 replaces the header with
``opencode/<ver>`` on every call, so those arms are proven here instead:

* a **module hook**: an OpenCode plugin, auto-loaded from the cell's
  ``$XDG_CONFIG_HOME/opencode/plugin/`` dir, runs inside the opencode process
  and logs the path and ``package.json`` version of every
  ``@ai-sdk/anthropic`` module present in the process module registry;
* an **image scan** for any other copy on the module resolution roots that
  could have loaded instead;
* for compiled-in builds, the version the binary scanner
  (``obench.provider_embedded``) reads from the binary, with the hook showing
  that no outside copy was loaded.

``judge_load_proof`` turns those into ``load_proof_basis`` (``user_agent`` |
``module_hook``) and a pass / fail / unproven verdict. Mixed versions fail. A
missing hook log is unproven, never a pass.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

BASIS_USER_AGENT = "user_agent"
BASIS_MODULE_HOOK = "module_hook"
BASES = (BASIS_USER_AGENT, BASIS_MODULE_HOOK)
PASS, FAIL, UNPROVEN = "pass", "fail", "unproven"
HOOK_FILE = "obench-load-proof.js"
HOOK_LOG_ENV = "OBENCH_LOAD_PROOF_LOG"
PKG = ("@ai-sdk", "anthropic")


def hook_script(log_path: str) -> str:
    """OpenCode plugin source. Logs JSONL to ``log_path``.

    A ``start`` line proves the hook ran in this process. Each ``loaded`` line
    is one ``@ai-sdk/anthropic`` module seen in ``require.cache`` or Bun's ESM
    ``Loader.registry``, with the version from the nearest ``package.json``.
    Registry polling only reads; the hook makes no network call.
    """
    log = json.dumps(log_path)
    return f"""import {{ appendFileSync, readFileSync, existsSync }} from "node:fs";
import {{ dirname, join }} from "node:path";
const LOG = process.env.{HOOK_LOG_ENV} || {log};
const seen = new Set();
function write(o) {{ try {{ appendFileSync(LOG, JSON.stringify({{ ...o, pid: process.pid, ts: Date.now() }}) + "\\n"); }} catch {{}} }}
function pkgDir(file) {{
  let d = dirname(file);
  for (let i = 0; i < 8 && d && d !== "/"; i++, d = dirname(d)) {{
    const p = join(d, "package.json");
    if (existsSync(p)) {{ try {{ const j = JSON.parse(readFileSync(p, "utf8")); if (j.name === "@ai-sdk/anthropic") return [d, String(j.version || "")]; }} catch {{}} }}
  }}
  return [null, ""];
}}
function keys() {{
  const out = [];
  try {{ for (const k of Object.keys(require.cache || {{}})) out.push(k); }} catch {{}}
  try {{ const r = globalThis.Loader && globalThis.Loader.registry; if (r) for (const k of r.keys()) out.push(String(k)); }} catch {{}}
  return out;
}}
function scan() {{
  for (const raw of keys()) {{
    const k = raw.replace(/^file:\\/\\//, "");
    if (!k.includes("/@ai-sdk/anthropic/")) continue;
    const [dir, version] = pkgDir(k);
    if (!dir || seen.has(dir)) continue;
    seen.add(dir);
    write({{ event: "loaded", path: dir, version }});
  }}
}}
export const ObenchLoadProof = async () => {{
  write({{ event: "start", bun: (process.versions && process.versions.bun) || "", argv0: process.argv0 || "" }});
  scan();
  const t = setInterval(scan, 500); if (t.unref) t.unref();
  process.on("exit", () => {{ scan(); write({{ event: "exit" }}); }});
  return {{ event: async () => {{ scan(); }} }};
}};
"""


def install_hook(config_home: str, log_path: str) -> str:
    """Write the plugin where OpenCode auto-loads it. Returns its path or ''."""
    d = os.path.join(config_home, "opencode", "plugin")
    try:
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, HOOK_FILE)
        Path(path).write_text(hook_script(log_path), encoding="utf-8")
    except OSError:
        return ""
    return path


def read_hook_log(path) -> dict | None:
    """``{"started": bool, "loaded": [{"path","version"}]}``; None if no log."""
    p = Path(path) if path else None
    if p is None or not p.is_file():
        return None
    started, loaded, seen = False, [], set()
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("event") == "start":
            started = True
        elif rec.get("event") == "loaded":
            key = (str(rec.get("path") or ""), str(rec.get("version") or ""))
            if key not in seen:
                seen.add(key)
                loaded.append({"path": key[0], "version": key[1]})
    return {"started": started, "loaded": loaded}


def scan_copies(roots: Iterable, exclude: Iterable = (), max_depth: int = 12) -> list[dict]:
    """Every ``@ai-sdk/anthropic/package.json`` under ``roots`` (symlinks not
    followed), minus anything under ``exclude`` (e.g. the read-only pin store,
    which is not on any resolution path)."""
    ex = [os.path.realpath(str(e)) for e in exclude if e]
    found, seen = [], set()
    for root in roots:
        if not root or not os.path.isdir(str(root)):
            continue
        base = os.path.realpath(str(root))
        for cur, dirs, _files in os.walk(base):
            if any(cur == e or cur.startswith(e + os.sep) for e in ex):
                dirs[:] = []
                continue
            if cur[len(base):].count(os.sep) >= max_depth:
                dirs[:] = []
            if os.path.basename(cur) == PKG[1] and os.path.basename(os.path.dirname(cur)) == PKG[0]:
                pj = os.path.join(cur, "package.json")
                if cur not in seen and os.path.isfile(pj):
                    seen.add(cur)
                    try:
                        ver = str(json.loads(Path(pj).read_text(encoding="utf-8")).get("version") or "")
                    except (OSError, ValueError):
                        ver = ""
                    found.append({"path": cur, "version": ver})
                dirs[:] = [d for d in dirs if d == "node_modules"]
    return sorted(found, key=lambda c: c["path"])


def judge_load_proof(*, pin: str, ua_version: str = "", hook: dict | None = None,
                     copies: list | None = None, embedded_version: str = "",
                     compiled: bool = False) -> dict:
    """Verdict for one arm.

    ``user_agent`` is used whenever the header carried a version. Otherwise
    ``module_hook``: the hook log must exist and have started; the loaded
    versions must agree (mixed fails) and equal the pin; the image scan must
    find no copy other than the loaded one. For a compiled-in build the
    binary's built-in version must equal the pin and the hook must show no
    outside copy loaded.
    """
    pin = str(pin or "").strip()
    ua = str(ua_version or "").strip()
    out = {"load_proof_basis": BASIS_USER_AGENT if ua else BASIS_MODULE_HOOK,
           "load_proof": UNPROVEN, "load_proof_reason": ""}

    def done(verdict, why):
        out["load_proof"], out["load_proof_reason"] = verdict, why
        return out

    if not pin:
        return done(UNPROVEN, "no pin")
    if ua:
        if ua.startswith("mixed:"):
            return done(FAIL, f"User-Agent mixed versions {ua[6:]}")
        return done(PASS, f"User-Agent {ua}") if ua == pin else done(FAIL, f"User-Agent {ua} != pin {pin}")
    if hook is None:
        return done(UNPROVEN, "module hook log missing")
    if not hook.get("started"):
        return done(UNPROVEN, "module hook did not start")
    loaded = hook.get("loaded") or []
    versions = sorted({str(e.get("version") or "") for e in loaded})
    out["module_hook_versions"] = versions
    out["module_hook_paths"] = sorted({str(e.get("path") or "") for e in loaded})
    copies = copies if copies is not None else None
    if len(versions) > 1:
        return done(FAIL, "mixed loaded versions " + ",".join(versions))
    if compiled:
        emb = str(embedded_version or "").strip()
        out["embedded_version"] = emb or None
        if loaded:
            return done(FAIL, f"compiled build loaded an outside copy {versions[0]} at {out['module_hook_paths'][0]}")
        if not emb:
            return done(UNPROVEN, "compiled build: binary scanner found no built-in version")
        if emb != pin:
            return done(FAIL, f"built-in {emb} != pin {pin}")
        return done(PASS, f"built-in {emb}, hook saw no outside copy")
    if not loaded:
        return done(UNPROVEN, "module hook saw no @ai-sdk/anthropic load")
    if versions[0] != pin:
        return done(FAIL, f"loaded {versions[0]} != pin {pin}")
    if copies is None:
        return done(UNPROVEN, "image scan missing")
    loaded_paths = {os.path.realpath(p) for p in out["module_hook_paths"]}
    others = [c for c in copies if os.path.realpath(str(c.get("path") or "")) not in loaded_paths]
    out["other_copies"] = others
    if others:
        return done(FAIL, "other copies could load: " + ", ".join(f"{c['path']}@{c['version']}" for c in others))
    return done(PASS, f"loaded {versions[0]} at {out['module_hook_paths'][0]}, no other copy")
