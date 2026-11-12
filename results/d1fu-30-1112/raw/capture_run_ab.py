#!/usr/bin/env python3
"""Run thesis.ab.run_ab with per-call request-body capture (observational only).

Same idea as the #245 cache-divergence runs (A+B, 29236b59, m245c-batch.py): wrap
proxy module functions in this process, call the originals unchanged, and write
what they saw. Nothing in the repo is edited; return values are passed through.

Per call, under <out>/request-bodies/<cell>/:
  NNNN.client.json        json.dumps of the body as parsed on receipt (before any
                          proxy edit); written only when it differs from pre_translate
  NNNN.pre_translate.bin  exact bytes handed to translate_body (= client bytes when
                          the proxy made no edit)
  NNNN.forwarded.bin      exact bytes sent upstream to Vertex
  meta.jsonl              one line per call: index, route, kind, sha256 + sizes
Capture failures are logged to <out>/request-bodies/errors.log and never raised.
"""
import hashlib, json, os, runpy, sys, threading, time, traceback

out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "/tmp"
ROOT = os.path.join(out, "request-bodies")
if __name__ == "__main__":
    os.makedirs(ROOT, exist_ok=True)

import thesis.ab.vertex_anthropic_proxy as v

_tl = threading.local()
_lock = threading.Lock()
_count = {}


def _err(msg):
    try:
        with open(os.path.join(ROOT, "errors.log"), "a") as fh:
            fh.write(time.strftime("%F %T %Z ") + msg + "\n")
    except Exception:
        pass


_orig_split = v.split_cell_path
_orig_role = v.classify_call_role
_orig_translate = v.translate_body


def split_cell_path(path):
    res = _orig_split(path)
    try:
        _tl.cell = res[0]
        _tl.route = res[1]
        _tl.client = None
    except Exception:
        _err("split: " + traceback.format_exc())
    return res


def classify_call_role(data, header):
    try:
        if getattr(_tl, "client", None) is None:
            _tl.client = json.dumps(data).encode("utf-8")
    except Exception:
        _err("role: " + traceback.format_exc())
    return _orig_role(data, header)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def translate_body(path, body):
    kind, fwd = _orig_translate(path, body)
    try:
        cell = getattr(_tl, "cell", None) or "_nocell"
        client = getattr(_tl, "client", None)
        with _lock:
            n = _count.get(cell, 0) + 1
            _count[cell] = n
        d = os.path.join(ROOT, cell)
        os.makedirs(d, exist_ok=True)
        pre = bytes(body)
        with open(os.path.join(d, "%04d.pre_translate.bin" % n), "wb") as fh:
            fh.write(pre)
        with open(os.path.join(d, "%04d.forwarded.bin" % n), "wb") as fh:
            fh.write(fwd)
        same = client is not None and (client == pre or json.loads(pre) == json.loads(client))
        if client is not None and client != pre:
            with open(os.path.join(d, "%04d.client.json" % n), "wb") as fh:
                fh.write(client)
        meta = {
            "i": n, "cell": cell, "route": path, "kind": kind,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "pre_translate_sha256": _sha(pre), "pre_translate_bytes": len(pre),
            "forwarded_sha256": _sha(fwd), "forwarded_bytes": len(fwd),
            "client_sha256": _sha(client) if client is not None else None,
            "client_bytes_equal_pre_translate": client == pre if client is not None else None,
            "client_json_equal_pre_translate": same,
        }
        with _lock:
            with open(os.path.join(d, "meta.jsonl"), "a") as fh:
                fh.write(json.dumps(meta, sort_keys=True) + "\n")
    except Exception:
        _err("translate: " + traceback.format_exc())
    finally:
        _tl.client = None
    return kind, fwd


if __name__ == "__main__":
  v.split_cell_path = split_cell_path
  v.classify_call_role = classify_call_role
  v.translate_body = translate_body
  with open(os.path.join(ROOT, "CAPTURE.txt"), "w") as fh:
      fh.write("capture wrapper active pid=%d argv=%s\n" % (os.getpid(), json.dumps(sys.argv[1:])))

if __name__ == "__main__":
    sys.argv = ["thesis.ab.run_ab"] + sys.argv[1:]
    runpy.run_module("thesis.ab.run_ab", run_name="__main__", alter_sys=True)
