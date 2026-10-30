"""The base agent's run loop.

One loop for every config. Each step: M6 may rewrite history, the request is
built from M1 (system), M2 (tools, including M7/M9/M10 contributions), M4
(sampling) and M3 (cache marks), sent through M12 (retries), and every tool
call passes M13 (permissions) before it runs. M11 caps steps and may append a
note after tool results. M5 runs once before the loop.
"""
from __future__ import annotations

import copy
import json
import urllib.error
import urllib.request

from thesis.base_agent import config as C
from thesis.base_agent import modules
from thesis.base_agent.interfaces import ModelClient, ModelError, RunContext, ToolError

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
CALL_ROLE_HEADER = "X-OB-Call-Role"  # thesis/ab/vertex_anthropic_proxy.py


class HttpModelClient(ModelClient):
    """Non-streaming Anthropic Messages client for the counting proxy."""

    def __init__(self, base_url: str, api_key: str = "openbench-routed-synthetic",
                 timeout_s: float = 600.0, anthropic_version: str = "2023-06-01"):
        base = base_url.rstrip("/")
        self.url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
        self.api_key, self.timeout_s, self.version = api_key, timeout_s, anthropic_version

    def complete(self, request, role="main"):
        body = json.dumps(request).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "content-type": "application/json", "x-api-key": self.api_key,
            "anthropic-version": self.version, CALL_ROLE_HEADER: role})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ModelError(f"HTTP {exc.code}: {detail}", exc.code, exc.code in RETRYABLE_STATUS) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ModelError(f"transport: {exc}", None, True) from exc


class _RoleClient(ModelClient):
    """Forces one call role, so a subagent's calls are tagged at the proxy."""

    def __init__(self, inner: ModelClient, role: str):
        self.inner, self.role = inner, role

    def complete(self, request, role="main"):
        return self.inner.complete(request, role=self.role if role == "main" else role)


class Agent:
    def __init__(self, resolved: dict, version: dict, client: ModelClient, model: str,
                 workdir: str, instruction: str, depth: int = 0):
        self.resolved, self.version = resolved, version
        self.model, self.depth = model, depth
        self.m = {slot: modules.build(slot, spec["impl"], spec["params"])
                  for slot, spec in resolved["modules"].items()}
        self.ctx = RunContext(workdir=workdir, instruction=instruction, model=model, client=client,
                              executor=self.m["M8"], env=modules.environment(workdir), depth=depth)
        self.ctx.spawn = self._spawn

    @classmethod
    def from_config(cls, name: str, arm: str, client: ModelClient, model: str, workdir: str,
                    instruction: str, fixed: dict | None = None) -> "Agent":
        cfg = C.load_config(name)
        fixed = fixed if fixed is not None else C.load_fixed()
        resolved = C.resolve(cfg, fixed, arm)
        return cls(resolved, C.version_record(cfg, fixed, resolved), client, model, workdir, instruction)

    def _spawn(self, description: str, prompt: str) -> str:
        """Run a child agent with the same modules minus delegation and side
        calls. Its calls are tagged ``side:subagent``."""
        child = copy.deepcopy(self.resolved)
        child["modules"]["M10"] = {"impl": "none", "params": {}}
        child["modules"]["M5"] = {"impl": "none", "params": {}}
        sub_m2 = child["modules"]["M2"]["params"]
        sub_m2["tools"] = [t for t in sub_m2.get("tools", []) if t in self.subagent_tools()]
        agent = Agent(child, self.version, _RoleClient(self.ctx.client, "side:subagent"), self.model,
                      self.ctx.workdir, prompt, depth=self.depth + 1)
        result = agent.run()
        self.ctx.event("subagent", description=description, stop=result["stop"],
                       steps=result["steps"], model_calls=result["model_calls"])
        return result["final_text"] or f"(subagent stopped: {result['stop']})"

    def subagent_tools(self) -> set[str]:
        planner = {t.name for t in self.m["M9"].tools(self.ctx)}
        delegation = {t.name for t in self.m["M10"].tools(self.ctx)}
        return set(self.resolved["modules"]["M2"]["params"].get("tools", [])) - planner - delegation

    def tools(self):
        contributed = {}
        for slot in ("M7", "M9", "M10"):
            for t in self.m[slot].tools(self.ctx):
                if t.name in contributed:
                    raise ValueError(f"tool {t.name} contributed twice")
                t.slot = slot
                contributed[t.name] = t
        return self.m["M2"].tools(self.ctx, contributed)

    def build_request(self, messages: list[dict], tools) -> dict:
        system = [{"type": "text", "text": b} for b in self.m["M1"].system_blocks(self.ctx, tools)]
        req = {"model": self.model, "system": system, "messages": copy.deepcopy(messages)}
        if tools:
            req["tools"] = self.m["M2"].render(tools)
        self.m["M4"].apply(req)
        self.m["M3"].apply(req)
        return req

    def _run_tool(self, block: dict, by_name: dict) -> dict:
        name, args = block.get("name"), block.get("input") or {}
        out = {"type": "tool_result", "tool_use_id": block.get("id")}
        refusal = self.m["M13"].check(name, args, self.ctx)
        if refusal is not None:
            return {**out, "content": refusal, "is_error": True}
        t = by_name.get(name)
        if t is None:
            return {**out, "content": f"Unknown tool: {name}", "is_error": True}
        try:
            return {**out, "content": t.handler(args, self.ctx)}
        except ToolError as exc:
            return {**out, "content": str(exc), "is_error": True}
        except Exception as exc:  # a tool bug must not end the run silently
            self.ctx.event("tool_exception", tool=name, error=f"{type(exc).__name__}: {exc}")
            return {**out, "content": f"{type(exc).__name__}: {exc}", "is_error": True}

    def run(self) -> dict:
        ctx, m = self.ctx, self.m
        if self.depth == 0:
            m["M5"].on_start(ctx)
        tools = self.tools()
        by_name = {t.name: t for t in tools}
        messages = [{"role": "user", "content": m["M1"].first_user_message(ctx)}]
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": 0}
        tool_counts: dict[str, int] = {}
        last_usage, steps, calls, stop, final_text = None, 0, 0, "max_steps", ""
        while steps < m["M11"].max_steps:
            messages = m["M6"].prepare(messages, last_usage, ctx)
            req = self.build_request(messages, tools)
            try:
                resp = m["M12"].call(lambda: ctx.client.complete(req, role="main"), ctx)
            except ModelError as exc:
                ctx.event("model_error", status=exc.status, error=str(exc)[:500])
                stop = "model_error"
                break
            calls += 1
            steps += 1
            last_usage = resp.get("usage") or {}
            for k in usage:
                usage[k] += int(last_usage.get(k) or 0)
            content = resp.get("content") or []
            messages.append({"role": "assistant", "content": content})
            final_text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            if m["M11"].should_stop(resp, ctx):
                stop = "end_turn"
                break
            uses = [b for b in content if b.get("type") == "tool_use"]
            results = []
            for b in uses:
                tool_counts[b.get("name")] = tool_counts.get(b.get("name"), 0) + 1
                results.append(self._run_tool(b, by_name))
            note = m["M11"].after_tools(uses, results, ctx)
            turn = list(results)
            if note:
                turn.append({"type": "text", "text": note})
            messages.append({"role": "user", "content": turn})
        return {"stop": stop, "steps": steps, "model_calls": calls, "final_text": final_text,
                "usage": usage, "tool_calls": tool_counts, "events": ctx.events,
                "version": self.version, "messages": messages}
