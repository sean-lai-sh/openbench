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
import shutil
import tempfile
import threading
import time
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
    "OBENCH_ADC_METADATA", "GOOGLE_APPLICATION_CREDENTIALS", "OBENCH_CELL_TEMP_ROOT",
)


class Stub:
    def __init__(self):
        self.hits: list[str] = []
        self.requests: list[dict] = []
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
                stub.requests.append({"method": "POST", "path": self.path,
                                      "headers": dict(self.headers.items()),
                                      "body": raw.decode("utf-8", "replace")})
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


def build_channel_of(binary: str) -> str:
    """``build_channel`` from the build stamp next to the binary.

    Stamps written before the column existed have no key; those builds ran
    with ``OPENCODE_CHANNEL`` unset, recorded as ``default``.
    """
    try:
        stamp = json.loads((Path(binary).parent / "build-stamp.json").read_text())
    except (OSError, ValueError):
        return ""
    return str(stamp.get("build_channel") or "default")


def check_side(binary: str, cache: str, sha: str, side: str, pr: str, timeout_s: int = 120,
               capture: Path | None = None, label: str = "") -> dict:
    out = {"pr": pr, "side": side, "sha": sha, "binary": binary,
           "build_channel": build_channel_of(binary),
           "cell_image": os.environ.get("OBENCH_CELL_IMAGE", ""),
           "strace": "off" if os.environ.get("OBENCH_PROVIDER_TRACE") == "0"
           or not shutil.which("strace") else "on"}
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
        with tempfile.TemporaryDirectory(prefix="stub-ready-") as tmp, \
                tempfile.TemporaryDirectory(prefix="stub-cell-") as cell:
            # Cells get a temp root; the strace trace lands there, outside the
            # opencode cache that pre-2026 builds wipe at startup.
            os.environ["OBENCH_CELL_TEMP_ROOT"] = cell
            t0 = time.monotonic()
            row = adapter.run("Reply with ok.", tmp, "claude-opus-5-5", timeout_s)
            out["wall_s"] = round(time.monotonic() - t0, 3)
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        return {**out, "ready": False, "reason": f"exception: {exc!r}"[:300]}
    finally:
        stub.close()
        if capture is not None:
            capture.mkdir(parents=True, exist_ok=True)
            name = (label or sha or "side").replace("/", "_")
            with open(capture / f"{name}.requests.jsonl", "w") as fh:
                for req in stub.requests:
                    fh.write(json.dumps(req, sort_keys=True) + "\n")
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


def ran(r: dict) -> list[str]:
    """Reasons a run did not start a session and reach the stub."""
    reasons = []
    if not r.get("stub_requests"):
        reasons.append("no request reached stub")
    if "opencode run [message" in str(r.get("output_tail") or ""):
        reasons.append("printed usage")
    if str(r.get("reason", "")).startswith(("binary missing", "assess", "exception", "toolchain")):
        reasons.append(r["reason"])
    return reasons


def check_control(label: str, rebuild: str, original: str, sha: str, cache: str,
                  timeout_s: int, capture: Path | None) -> list[dict]:
    """A control passes when both binaries run and reach the stub, and the
    probe records the same provider version for the rebuild as for its
    original. Controls have no manifest pin; none is needed."""
    rows = []
    for kind, path in (("rebuild", rebuild), ("original", original)):
        r = check_side(path, cache, sha, "", "", timeout_s, capture, f"{label}-{kind}")
        r["label"] = f"{label}/{kind}"
        rows.append(r)
    reasons = []
    for r in rows:
        reasons += [f"{r['label']}: {x}" for x in ran(r)]
    a, b = (str(r.get("provider_loaded_version") or "") for r in rows)
    if not a or not b:
        reasons.append(f"probe recorded no version (rebuild {a or 'none'}, original {b or 'none'})")
    elif a != b:
        reasons.append(f"provider differs: rebuild {a} != original {b}")
    for r in rows:
        r["ready"] = not reasons
        r["reason"] = "; ".join(reasons) or f"ok: both loaded {a}"
    return rows


FIELDS = ["label", "pr", "side", "sha", "ready", "reason", "build_channel", "cell_image",
          "strace", "wall_s", "assess", "pin",
          "provider_loaded_version", "provider_loaded_source", "provider_loaded_mismatch",
          "stub_requests", "completed", "exit_error", "cmd", "binary", "output_tail"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sides", type=Path, help="JSON {pr: {without: sha, with: sha}}")
    p.add_argument("--bin-root", type=Path, required=True, help="dir holding <sha>/opencode")
    p.add_argument("--cache", type=Path, required=True, help="build cache (provider-pins store)")
    p.add_argument("--binary", action="append", default=[],
                   help="extra label=path[=sha] checked with no PR side")
    p.add_argument("--control", action="append", default=[],
                   help="label=rebuild_path=original_path=sha; passes on same loaded provider")
    p.add_argument("--capture", type=Path, help="write each run's stub requests here")
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
        r = check_side(binary, str(a.cache), sha, side, pr, a.timeout, a.capture, label)
        r["label"] = label
        rows.append(r)
        print(f"{label} ready={r['ready']} {r['reason']}", flush=True)
    for spec in a.control:
        label, rebuild, original, sha = spec.split("=")
        for r in check_control(label, rebuild, original, sha, str(a.cache), a.timeout, a.capture):
            rows.append(r)
            print(f"{r['label']} ready={r['ready']} {r['reason']}", flush=True)
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
