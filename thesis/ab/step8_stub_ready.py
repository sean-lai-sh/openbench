"""Actual-run readiness for step-8 OpenCode sides, against a local stub.

Each side's binary runs through ``obench.adapters.opencode.run``, the same
path a cell takes (exact argv, isolated env, provider pin, #156 probe). The
Anthropic endpoint is a stub on 127.0.0.1 that answers every request with a
canned "ok" stream, so no model is called. A side is ready only when:

* compat assessment (``models`` listing) finds the model,
* a session starts and at least one request reaches the stub,
* the #156 probe records the pinned ``@ai-sdk/anthropic`` version.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from thesis.ab.compat import assess

_EVENTS = [
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_stub", "type": "message", "role": "assistant", "model": "stub",
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0,
                             "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "text_delta", "text": "ok"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {"type": "message_delta",
                       "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                       "usage": {"output_tokens": 1}}),
    ("message_stop", {"type": "message_stop"}),
]
_KEYS = (
    "OBENCH_OPENCODE_BIN", "OBENCH_OPENCODE_CONFIG_JSON",
    "OBENCH_OPENCODE_PERMISSION_CONFIG", "OBENCH_OPENCODE_PROXY",
    "OBENCH_ADC_METADATA", "GOOGLE_APPLICATION_CREDENTIALS",
)


class Stub:
    def __init__(self):
        self.hits: list[str] = []
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _body(self):
                n = int(self.headers.get("content-length") or 0)
                return self.rfile.read(n) if n else b""

            def do_POST(self):
                raw = self._body()
                stub.hits.append(self.path)
                try:
                    streaming = bool(json.loads(raw or b"{}").get("stream"))
                except ValueError:
                    streaming = False
                if not self.path.rstrip("/").endswith("/messages"):
                    self._json({})
                    return
                if not streaming:
                    self._json({"id": "msg_stub", "type": "message", "role": "assistant",
                                "model": "stub", "content": [{"type": "text", "text": "ok"}],
                                "stop_reason": "end_turn", "stop_sequence": None,
                                "usage": {"input_tokens": 1, "output_tokens": 1}})
                    return
                body = "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in _EVENTS).encode()
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                stub.hits.append("GET " + self.path)
                self._json({"data": []})

            def _json(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def check_side(binary: str, cache: str, sha: str, side: str, pr: str, timeout_s: int = 120) -> dict:
    out = {"pr": pr, "side": side, "sha": sha, "binary": binary}
    if not Path(binary).is_file():
        return {**out, "ready": False, "reason": "binary missing"}
    stub = Stub()
    saved = {k: os.environ.get(k) for k in _KEYS}
    try:
        a = assess(binary, route="proxy", proxy_url=stub.url)
        out["assess"] = f"{a.status}: {a.reason}"
        if a.status != "configured" or not a.proxy:
            return {**out, "ready": False, "reason": f"assess {a.status}: {a.reason}"}
        # Same proxy decoration a cell gets in run_ab: toolchain bun, lockfile
        # pin, then the manifest pin for this side.
        from thesis.ab.run_ab import _decorate_toolchain, _overlay_provider_pin
        state = {"ok": True, "harness": "opencode", "proxy": dict(a.proxy)}
        state, why = _decorate_toolchain(state, Path(cache), sha, "") if sha else (state, None)
        if why:
            return {**out, "ready": False, "reason": f"toolchain: {why}"}
        state = _overlay_provider_pin(state, Path(cache), {"sha": sha, "side": side, "pr": pr})
        proxy = state["proxy"]
        pin = str(proxy.get("anthropic_sdk") or "")
        out["pin"] = pin
        for k in ("OBENCH_ADC_METADATA", "GOOGLE_APPLICATION_CREDENTIALS"):
            os.environ.pop(k, None)
        os.environ["OBENCH_OPENCODE_BIN"] = binary
        if a.config:
            os.environ["OBENCH_OPENCODE_CONFIG_JSON"] = json.dumps(a.config)
        else:
            os.environ.pop("OBENCH_OPENCODE_CONFIG_JSON", None)
        os.environ["OBENCH_OPENCODE_PERMISSION_CONFIG"] = "1" if a.permission_config else "0"
        os.environ["OBENCH_OPENCODE_PROXY"] = json.dumps(proxy)
        from obench.adapters import opencode as adapter
        with tempfile.TemporaryDirectory(prefix="stub-ready-") as tmp:
            row = adapter.run("Reply with ok.", tmp, "claude-opus-5-5", timeout_s)
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        return {**out, "ready": False, "reason": f"exception: {exc!r}"[:300]}
    finally:
        stub.close()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    msgs = [h for h in stub.hits if h.rstrip("/").endswith("/messages")]
    loaded = str(row.get("provider_loaded_version") or "")
    out.update({
        "stub_requests": len(msgs),
        "exit_error": str(row.get("error") or ""),
        "completed": row.get("completed"),
        "provider_loaded_version": loaded,
        "provider_loaded_source": row.get("provider_loaded_source"),
        "provider_loaded_mismatch": row.get("provider_loaded_mismatch"),
        "cmd": json.dumps((row.get("cmd") or [])[:-1]),
        "output_tail": str(row.get("output_tail") or "")[-300:],
    })
    reasons = []
    if not msgs:
        reasons.append("no request reached stub")
    if "usage" in out["output_tail"].lower() and "opencode run [message" in out["output_tail"]:
        reasons.append("printed usage")
    if not pin:
        reasons.append("no pin")
    elif loaded != pin:
        reasons.append(f"probe loaded {loaded or 'none'} != pin {pin}")
    if row.get("provider_loaded_mismatch"):
        reasons.append("provider_loaded_mismatch")
    out["ready"] = not reasons
    out["reason"] = "; ".join(reasons) or "ok"
    return out


FIELDS = ["label", "pr", "side", "sha", "ready", "reason", "assess", "pin",
          "provider_loaded_version", "provider_loaded_source", "provider_loaded_mismatch",
          "stub_requests", "completed", "exit_error", "cmd", "binary", "output_tail"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sides", type=Path, help="JSON {pr: {without: sha, with: sha}}")
    p.add_argument("--bin-root", type=Path, required=True, help="dir holding <sha>/opencode")
    p.add_argument("--cache", type=Path, required=True, help="build cache (provider-pins store)")
    p.add_argument("--binary", action="append", default=[],
                   help="extra label=path[=sha] checked with no PR side (controls)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=120)
    a = p.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    jobs = []
    if a.sides:
        for pr, sides in sorted(json.loads(a.sides.read_text()).items()):
            for side in ("without", "with"):
                sha = sides.get(side)
                if sha:
                    jobs.append((f"{pr}/{side}", str(a.bin_root / sha / "opencode"), sha, side, pr))
    for spec in a.binary:
        parts = spec.split("=")
        jobs.append((parts[0], parts[1], parts[2] if len(parts) > 2 else "", "", ""))
    rows = []
    for label, binary, sha, side, pr in jobs:
        r = check_side(binary, str(a.cache), sha, side, pr, a.timeout)
        r["label"] = label
        rows.append(r)
        print(f"{label} ready={r['ready']} {r['reason']}", flush=True)
    with open(a.out / "stub_ready.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    n = sum(1 for r in rows if r["ready"])
    (a.out / "stub_ready_summary.txt").write_text(
        f"ready {n}/{len(rows)}\n" + "".join(
            f"NOT READY {r['label']}: {r['reason']}\n" for r in rows if not r["ready"]))
    print(f"ready {n}/{len(rows)}")
    return 0 if n == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
