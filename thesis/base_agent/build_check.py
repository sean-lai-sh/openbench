"""AC3 build check: system-prompt and tool-schema bytes, base config vs real harness.

Brief section 1.6: "System-prompt + tool-schema bytes at the proxy: must match
the real harness's captured request within 5% (this is a build check, run
before any scored cell)."

Both sides are captured the same way, at a loopback stub that stands where the
counting proxy stands and answers every request with a canned end_turn. No
model is called and nothing is billed:

* base config: ``capture`` here runs the base agent against the stub;
* real harness: ``python -m thesis.ab.step8_stub_ready --capture DIR`` runs the
  real OpenCode binary through the cell adapter against the same kind of
  stub. The file format is the same: one ``{method, path, headers, body}``
  JSON object per line in ``*.requests.jsonl``.

``compare`` picks the first main-loop request on each side (the first
``/messages`` or ``/chat/completions`` request that carries tools and is not
tagged as a side call), and measures:

* ``system``: UTF-8 bytes of all system text (Anthropic ``system`` string or
  text blocks; ``role: system`` messages for chat completions);
* ``tools``: bytes of the tools array as canonical JSON (sorted keys, no
  whitespace, ``cache_control`` removed), so key order and cache marks don't
  count.

A config passes when system bytes and tool bytes are each within the
tolerance (default 5%) of the real harness. The combined figure is reported
too. Tool names, order, and sampling fields (max_tokens, temperature,
thinking) are reported but do not affect the pass/fail result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from thesis.base_agent import config as C
from thesis.base_agent.agent import CALL_ROLE_HEADER, Agent, HttpModelClient

TOLERANCE = 0.05
SAMPLING_KEYS = ("max_tokens", "temperature", "top_p", "top_k", "thinking", "reasoning_effort")
DEFAULT_INSTRUCTION = "Reply with ok."


# --- capture ----------------------------------------------------------------
class CaptureStub:
    """Loopback Messages endpoint that records each request and replies
    end_turn "ok" (non-streaming, or a minimal SSE stream when asked)."""

    _REPLY = {"id": "msg_stub", "type": "message", "role": "assistant", "model": "stub",
              "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
              "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}

    def __init__(self):
        self.requests: list[dict] = []
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(n) if n else b""
                stub.requests.append({"method": "POST", "path": self.path,
                                      "headers": dict(self.headers.items()),
                                      "body": raw.decode("utf-8", "replace")})
                payload = json.dumps(stub._REPLY).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def capture_base(config: str, arm: str, model: str, workdir: str | None = None,
                 instruction: str = DEFAULT_INSTRUCTION) -> tuple[list[dict], dict]:
    """Run the base agent once against a capture stub. Returns the captured
    requests and the config's version record."""
    stub = CaptureStub()
    tmp = None
    try:
        if workdir is None:
            tmp = tempfile.TemporaryDirectory(prefix="ac3-capture-")
            workdir = tmp.name
        agent = Agent.from_config(config, arm, HttpModelClient(stub.url), model, workdir, instruction)
        agent.run()
        return list(stub.requests), agent.version
    finally:
        stub.close()
        if tmp is not None:
            tmp.cleanup()


def write_requests(path: Path, requests: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        for r in requests:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def load_requests(path: Path) -> list[dict]:
    """``*.requests.jsonl`` (one request per line), or a single JSON request
    body, which is wrapped as one POST to /v1/messages."""
    text = Path(path).read_text()
    stripped = text.strip()
    if stripped.startswith("{") and "\n" not in stripped:
        obj = json.loads(stripped)
        if "body" in obj and "path" in obj:
            return [obj]
        return [{"method": "POST", "path": "/v1/messages", "headers": {}, "body": stripped}]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# --- measurement --------------------------------------------------------------
def _body(req: dict) -> dict:
    b = req.get("body")
    if isinstance(b, dict):
        return b
    try:
        return json.loads(b or "{}")
    except ValueError:
        return {}


def _role_header(req: dict) -> str:
    for k, v in (req.get("headers") or {}).items():
        if k.lower() == CALL_ROLE_HEADER.lower():
            return str(v).strip().lower()
    return ""


def main_request(requests: list[dict]) -> dict:
    """First model request that carries tools and is not a side call."""
    for req in requests:
        path = str(req.get("path") or "").split("?")[0].rstrip("/")
        if not (path.endswith("/messages") or path.endswith("/chat/completions")):
            continue
        if _role_header(req).startswith("side"):
            continue
        body = _body(req)
        if body.get("tools"):
            return req
    raise ValueError("no main-loop request with tools in the capture")


def _strip_cache(x):
    if isinstance(x, dict):
        return {k: _strip_cache(v) for k, v in x.items() if k != "cache_control"}
    if isinstance(x, list):
        return [_strip_cache(v) for v in x]
    return x


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _tool_name(t: dict) -> str:
    return str(t.get("name") or (t.get("function") or {}).get("name") or "")


def measure(body: dict) -> dict:
    system = _text_of(body.get("system"))
    blocks = len(body["system"]) if isinstance(body.get("system"), list) else (1 if system else 0)
    for m in body.get("messages") or []:  # chat-completions style
        if m.get("role") in ("system", "developer"):
            system += _text_of(m.get("content"))
            blocks += 1
    tools = _strip_cache(body.get("tools") or [])
    tools_json = json.dumps(tools, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "system_bytes": len(system.encode("utf-8")),
        "system_blocks": blocks,
        "tools_bytes": len(tools_json.encode("utf-8")),
        "tool_names": [_tool_name(t) for t in tools],
        "sampling": {k: body[k] for k in SAMPLING_KEYS if k in body},
        "model": body.get("model"),
    }


def _ratio(base: int, real: int, tol: float) -> dict:
    delta = (base - real) / real if real else (0.0 if base == 0 else float("inf"))
    return {"base": base, "real": real, "delta_pct": round(100 * delta, 2), "pass": abs(delta) <= tol}


def compare(base: dict, real: dict, tolerance: float = TOLERANCE) -> dict:
    sys_r = _ratio(base["system_bytes"], real["system_bytes"], tolerance)
    tool_r = _ratio(base["tools_bytes"], real["tools_bytes"], tolerance)
    comb = _ratio(base["system_bytes"] + base["tools_bytes"], real["system_bytes"] + real["tools_bytes"], tolerance)
    bn, rn = base["tool_names"], real["tool_names"]
    return {
        "tolerance_pct": 100 * tolerance,
        "system": sys_r,
        "tools": tool_r,
        "combined": comb,
        "tool_names": {"base": bn, "real": rn, "missing_in_base": [n for n in rn if n not in bn],
                       "extra_in_base": [n for n in bn if n not in rn], "same_order": bn == rn},
        "sampling": {"base": base["sampling"], "real": real["sampling"],
                     "match": base["sampling"] == real["sampling"]},
        "pass": sys_r["pass"] and tool_r["pass"],
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def report(base_path: Path, real_path: Path, version: dict | None, tolerance: float = TOLERANCE) -> dict:
    base_req, real_req = main_request(load_requests(base_path)), main_request(load_requests(real_path))
    base_m, real_m = measure(_body(base_req)), measure(_body(real_req))
    comparison = compare(base_m, real_m, tolerance)
    return {"check": "stage4-ac3-build-check", "verdict": "PASS" if comparison["pass"] else "FAIL",
            "comparison": comparison,
            "base": {"capture": str(base_path), "sha256": _sha(base_path), **base_m},
            "real": {"capture": str(real_path), "sha256": _sha(real_path), **real_m},
            "version": version}


def render(rep: dict) -> str:
    c = rep["comparison"]
    v = rep.get("version") or {}
    lines = [f"AC3 build check: {rep['verdict']}  (config {v.get('config_name', '?')}, arm {v.get('arm', '?')}, "
             f"base_agent_version {v.get('base_agent_version', '?')})",
             f"{'':10}{'base':>10}{'real':>10}{'delta':>9}  within {c['tolerance_pct']:g}%"]
    for k in ("system", "tools", "combined"):
        r = c[k]
        lines.append(f"{k:10}{r['base']:>10}{r['real']:>10}{r['delta_pct']:>8.2f}%  {'yes' if r['pass'] else 'NO'}")
    t = c["tool_names"]
    lines.append(f"tools: base {len(t['base'])}, real {len(t['real'])}; same order: {t['same_order']}")
    if t["missing_in_base"] or t["extra_in_base"]:
        lines.append(f"  missing in base: {t['missing_in_base']}  extra in base: {t['extra_in_base']}")
    s = c["sampling"]
    lines.append(f"sampling: base {json.dumps(s['base'], sort_keys=True)} real {json.dumps(s['real'], sort_keys=True)}"
                 f"{'' if s['match'] else '  (differs: set [parity.M4] from the real values)'}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture", help="capture the base config's requests at a loopback stub")
    cmp_ = sub.add_parser("compare", help="compare a base capture with a real-harness capture")
    for sp in (cap, cmp_):
        sp.add_argument("--config", required=True)
        sp.add_argument("--arm", choices=C.ARMS, default="parity")
    cap.add_argument("--model", required=True)
    cap.add_argument("--workdir", help="defaults to a fresh temp dir; use the real capture's workdir to cancel cwd bytes")
    cap.add_argument("--instruction-file", type=Path)
    cap.add_argument("--out", type=Path, required=True, help="*.requests.jsonl to write")
    cmp_.add_argument("--base", type=Path, required=True)
    cmp_.add_argument("--real", type=Path, required=True)
    cmp_.add_argument("--tolerance", type=float, default=TOLERANCE)
    cmp_.add_argument("--out", type=Path, help="write the JSON report here")
    a = p.parse_args(argv)
    if a.cmd == "capture":
        instr = a.instruction_file.read_text() if a.instruction_file else DEFAULT_INSTRUCTION
        reqs, version = capture_base(a.config, a.arm, a.model, a.workdir, instr)
        write_requests(a.out, reqs)
        print(json.dumps({"requests": len(reqs), "out": str(a.out), **version}, indent=2))
        return 0
    cfg, fixed = C.load_config(a.config), C.load_fixed()
    version = C.version_record(cfg, fixed, C.resolve(cfg, fixed, a.arm))
    rep = report(a.base, a.real, version, a.tolerance)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(rep, indent=2) + "\n")
    print(render(rep))
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
