"""One-command diagnostic for the gpt-oss early stop on the Vertex MaaS route (SEA-105).

On the VM the smoke's first gpt-oss call came back with finish ``stop``, 34
reasoning characters, no text and no tool calls, while Vertex billed ~37
completion tokens. The tool call seems to be lost inside the route. This
sends **one request per variant** straight to Vertex, without the proxy and
without OpenCode, and saves exactly what comes back:

==================  =============================================================
variant             what changes from the proxy's request
==================  =============================================================
proxy_stream        nothing (stream, as OpenCode + the proxy send it)
proxy_nonstream     ``stream: false``
tool_choice_auto    explicit ``tool_choice: "auto"`` (stream)
tools_in_system     tool definitions also written into the system prompt, as
                    Vertex's function-calling page recommends for gpt-oss (stream)
tools_in_system_ns  the same, non-stream
effort_medium       ``reasoning_effort: "medium"`` (non-stream; diagnosis only, the
                    study stays on high)
keep_special        ``skip_special_tokens: false`` (vLLM-style; may be rejected),
                    to see raw Harmony tokens (non-stream)
raw_completions     ``endpoints/openapi/completions`` with a hand-rendered Harmony
                    prompt (non-stream), to see if the tool call survives
                    without the chat-side parser
==================  =============================================================

That is 8 calls (×``--repeat``), a few cents at most. Output in ``--out``:
``<variant>.request.json``, ``<variant>.raw`` (bytes as received) and
``summary.json``; a table is printed. ``--from-wire`` replays the first main
gpt-oss request from a smoke's ``wire.jsonl`` (the exact OpenCode request)
instead of the built-in one.

    GOOGLE_CLOUD_PROJECT=... python3 -m obench.reflection.gptoss_diag --out /tmp/gptoss-diag \\
        [--from-wire /tmp/smoke-gpt-oss-120b/wire.jsonl] [--repeat 3]

No scored data: write ``--out`` outside results/ and data/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from obench.reflection import vertex_models as vm
from obench.reflection.gptoss_repair import extract_tool_call
from obench.reflection.wire_proxy import HARMONY_MARKERS, prepare_request, response_summary

MODEL = vm.resolve("gpt-oss-120b")


def _tool(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
        "required": required}}}


BUILTIN_REQUEST = {
    "model": "gpt-oss-120b-maas", "stream": True, "max_tokens": 32000,
    "tools": [
        _tool("read", "Read a file", {"filePath": "absolute path", "offset": "line", "limit": "lines"}, ["filePath"]),
        _tool("bash", "Run a shell command", {"command": "the command", "description": "what it does"}, ["command"]),
        _tool("edit", "Replace text in a file", {"filePath": "absolute path", "oldString": "old", "newString": "new"},
              ["filePath", "oldString", "newString"]),
        _tool("write", "Write a file", {"filePath": "absolute path", "content": "content"}, ["filePath", "content"]),
        _tool("list", "List a directory", {"path": "absolute path"}, []),
    ],
    "messages": [
        {"role": "system", "content": "You are OpenCode, a coding agent. Use the tools to inspect and change files. "
                                      "Working directory: /app."},
        {"role": "user", "content": "The unit tests in /app fail. Fix calculator.py so `python3 -m unittest` passes."},
    ],
}


def base_request(from_wire: Path | None) -> dict:
    if from_wire is None:
        sent, _, _ = prepare_request(MODEL, "/v1/chat/completions", BUILTIN_REQUEST)
        return sent
    for line in from_wire.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line) if line.strip() else {}
        if rec.get("route") == MODEL.key and rec.get("call_role") == "main":
            return rec["request"]  # already what the proxy sent upstream
    raise SystemExit(f"no main gpt-oss request in {from_wire}")


def tools_text(tools: list) -> str:
    return "\n".join(f"- {t['function']['name']}: {t['function'].get('description', '')} "
                     f"parameters={json.dumps(t['function'].get('parameters', {}))}" for t in tools)


def harmony_prompt(req: dict) -> str:
    """A minimal Harmony rendering (system, developer with the tool namespace, the conversation, open assistant)."""
    fns = "\n".join(f"// {t['function'].get('description', '')}\ntype {t['function']['name']} = "
                    f"(_: {json.dumps(t['function'].get('parameters', {}))}) => any;" for t in req.get("tools") or [])
    parts = ["<|start|>system<|message|>You are ChatGPT, a large language model trained by OpenAI.\n"
             f"Reasoning: {req.get('reasoning_effort', 'high')}\n\n# Valid channels: analysis, commentary, final. "
             "Channel must be included for every message.\nCalls to these tools must go to the commentary channel: "
             "'functions'.<|end|>"]
    system = "\n".join(m["content"] for m in req["messages"] if m["role"] == "system" and isinstance(m["content"], str))
    parts.append(f"<|start|>developer<|message|># Instructions\n\n{system}\n\n# Tools\n\n## functions\n\n"
                 f"namespace functions {{\n\n{fns}\n\n}} // namespace functions<|end|>")
    for m in req["messages"]:
        if m["role"] == "user":
            content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
            parts.append(f"<|start|>user<|message|>{content}<|end|>")
    return "".join(parts) + "<|start|>assistant"


def variants(base: dict) -> dict[str, tuple[str, dict]]:
    """name -> (endpoint kind, request body)."""
    def v(**changes):
        body = json.loads(json.dumps(base))
        for k, val in changes.items():
            if val is None:
                body.pop(k, None)
            else:
                body[k] = val
        if not body.get("stream"):
            body.pop("stream_options", None)
        return body

    sys_tools = json.loads(json.dumps(base["messages"]))
    note = "\n\n# Tools\nYou can call these functions when required:\n" + tools_text(base.get("tools") or [])
    if sys_tools and sys_tools[0]["role"] == "system" and isinstance(sys_tools[0]["content"], str):
        sys_tools[0]["content"] += note
    else:
        sys_tools.insert(0, {"role": "system", "content": note.strip()})
    completions = {"model": base["model"], "prompt": harmony_prompt(base), "max_tokens": base.get("max_tokens") or 4096,
                   "stream": False, "skip_special_tokens": False}
    return {
        "proxy_stream": ("chat", v(stream=True)),
        "proxy_nonstream": ("chat", v(stream=False)),
        "tool_choice_auto": ("chat", v(stream=True, tool_choice="auto")),
        "tools_in_system": ("chat", v(stream=True, messages=sys_tools)),
        "tools_in_system_ns": ("chat", v(stream=False, messages=sys_tools)),
        "effort_medium": ("chat", v(stream=False, reasoning_effort="medium")),
        "keep_special": ("chat", v(stream=False, skip_special_tokens=False)),
        "raw_completions": ("completions", completions),
    }


def describe(raw: bytes, stream: bool, request: dict, kind: str) -> dict:
    if kind == "completions":
        try:
            doc = json.loads(raw)
            choice = (doc.get("choices") or [{}])[0]
            text = choice.get("text") or ""
            return {"finish_reasons": [choice.get("finish_reason")], "text_chars": len(text),
                    "harmony_markers": [m for m in HARMONY_MARKERS if m in text], "usage": doc.get("usage"),
                    "text_tail": text[-600:], "recoverable_tool_call": extract_tool_call(text, request)}
        except (ValueError, AttributeError):
            return {"unparsed": raw[:600].decode("utf-8", "replace")}
    summary = response_summary(MODEL, raw, stream)
    reasoning, content = _texts(raw, stream)
    summary.update({"reasoning_tail": reasoning[-600:], "content_tail": content[-600:],
                    "harmony_markers_anywhere": [m for m in HARMONY_MARKERS if m in reasoning + content],
                    "recoverable_tool_call": extract_tool_call(content, request) or extract_tool_call(reasoning, request),
                    "usage": _usage(raw, stream)})
    from obench.reflection.gptoss_repair import repair
    _, record = repair(raw, stream, request)
    summary["route_repair"] = record  # what the proxy would hand OpenCode (None: passed through unchanged)
    return summary


def _texts(raw: bytes, stream: bool) -> tuple[str, str]:
    from obench.reflection.gptoss_repair import _parse_stream
    if stream:
        r, c = [], []
        for ev in _parse_stream(raw):
            for ch in ev.get("choices") or []:
                d = ch.get("delta") or {}
                r.append(d.get("reasoning_content") or d.get("reasoning") or "")
                c.append(d.get("content") or "")
        return "".join(r), "".join(c)
    try:
        msg = (json.loads(raw).get("choices") or [{}])[0].get("message") or {}
    except ValueError:
        return "", ""
    return msg.get("reasoning_content") or msg.get("reasoning") or "", msg.get("content") or ""


def _usage(raw: bytes, stream: bool):
    from obench.reflection.gptoss_repair import _parse_stream
    if stream:
        found = [ev["usage"] for ev in _parse_stream(raw) if isinstance(ev.get("usage"), dict)]
        return found[-1] if found else None
    try:
        return json.loads(raw).get("usage")
    except ValueError:
        return None


def call(url: str, body: dict, token: str) -> tuple[int | None, bytes, float]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return resp.status, resp.read(), time.monotonic() - t0
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), time.monotonic() - t0
    except OSError as exc:
        return None, str(exc).encode(), time.monotonic() - t0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--from-wire", type=Path, help="replay the first main gpt-oss request of this wire.jsonl")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", nargs="*", help="variant names to run (default: all)")
    args = parser.parse_args(argv)
    if any(p in ("results", "data") for p in args.out.resolve().parts):
        raise SystemExit("diagnostic output never goes under results/ or data/")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project:
        raise SystemExit("GOOGLE_CLOUD_PROJECT is not set")
    from thesis.ab.vertex_anthropic_proxy import AdcToken
    token = AdcToken()
    args.out.mkdir(parents=True, exist_ok=True)
    chat_url = MODEL.upstream_url(project, True)
    urls = {"chat": chat_url, "completions": re.sub(r"/chat/completions$", "/completions", chat_url)}
    base = base_request(args.from_wire)
    rows = []
    for name, (kind, body) in variants(base).items():
        if args.only and name not in args.only:
            continue
        for rep in range(args.repeat):
            tag = name if args.repeat == 1 else f"{name}.{rep}"
            (args.out / f"{tag}.request.json").write_text(json.dumps(body, indent=1), encoding="utf-8")
            status, raw, secs = call(urls[kind], body, token())
            (args.out / f"{tag}.raw").write_bytes(raw)
            row = {"variant": tag, "endpoint": kind, "stream": bool(body.get("stream")), "status": status,
                   "seconds": round(secs, 1), "bytes": len(raw)}
            tools_from = base if kind == "completions" else body  # the completions body has the tools in the prompt
            row.update(describe(raw, bool(body.get("stream")), tools_from, kind) if status == 200 else
                       {"error_head": raw[:400].decode("utf-8", "replace")})
            rows.append(row)
            u = row.get("usage") or {}
            print(f"{tag:22} {str(status):4} finish={row.get('finish_reasons')} tool_calls={row.get('tool_calls')} "
                  f"text={row.get('text_chars')} reasoning={row.get('reasoning_chars')} "
                  f"completion_tokens={u.get('completion_tokens')} markers={row.get('harmony_markers_anywhere') or row.get('harmony_markers')} "
                  f"recoverable={bool(row.get('recoverable_tool_call'))} "
                  f"repair={(row.get('route_repair') or {}).get('method')}:{(row.get('route_repair') or {}).get('tool')}", flush=True)
    (args.out / "summary.json").write_text(json.dumps({"url": chat_url.replace(f"/projects/{project}/", "/projects/<project>/"), "rows": rows},
                                                      indent=1), encoding="utf-8")
    print(f"wrote {args.out}/summary.json and per-variant .request.json / .raw")
    return 0


if __name__ == "__main__":
    sys.exit(main())
