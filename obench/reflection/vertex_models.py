"""The reflection loop's three Vertex models (SEA-105). Nothing else routes.

Every scored reflection-loop run uses exactly these models, all on Vertex AI.
IDs, locations and endpoints are confirmed against the docs listed in
``VERTEX_MODELS.md`` (read 2026-11-13). There is no Sonnet and no Qwen
entry, and ``resolve`` never falls back: an unknown or misspelled name
raises ``UnknownModel``.

Each model has one fixed upstream URL. The recording proxy
(``wire_proxy.py``) forwards there whatever model the client names, after
checking the client named this model, so the served model can't silently
change. The proxy also sets the model's thinking explicitly on every
request (``THINKING``); the client's own thinking setting is overridden and
the override recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

VERTEX_HOST = "https://aiplatform.googleapis.com"
FORBIDDEN_SUBSTRINGS = ("sonnet", "qwen")


class UnknownModel(KeyError):
    pass


@dataclass(frozen=True)
class VertexModel:
    key: str                 # the reflection loop's name for the model
    display: str
    vertex_id: str           # Vertex model ID
    publisher: str           # Vertex publisher
    location: str            # Vertex location in the URL path
    wire: str                # trace.WIRES: anthropic | gemini | openai_chat
    client_ids: tuple        # model names a client may ask for on this route
    thinking: dict           # the explicit thinking setting the proxy sends
    prices: dict             # USD per 1M tokens: input, output, cache_read, cache_write
    price_verified: bool
    price_source: str
    opencode_npm: str
    opencode_model: str      # model id in OpenCode's config / --model
    notes: tuple = field(default_factory=tuple)

    def upstream_url(self, project: str, stream: bool) -> str:
        base = f"{VERTEX_HOST}/v1/projects/{project}/locations/{self.location}"
        if self.wire == "openai_chat":
            return f"{base}/endpoints/openapi/chat/completions"
        if self.wire == "anthropic":
            verb = "streamRawPredict" if stream else "rawPredict"
            return f"{base}/publishers/{self.publisher}/models/{self.vertex_id}:{verb}"
        verb = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return f"{base}/publishers/{self.publisher}/models/{self.vertex_id}:{verb}"


MODELS = {
    "gemini-4-carbon": VertexModel(
        key="gemini-4-carbon", display="Gemini 4 Carbon", vertex_id="gemini-4-carbon", publisher="google",
        location="global", wire="gemini", client_ids=("gemini-4-carbon",),
        # LOW / MEDIUM (default) / HIGH; thinking_budget and MINIMAL are rejected with 400.
        # includeThoughts returns thought summaries (Carbon returns summaries only).
        thinking={"thinkingLevel": "HIGH", "includeThoughts": True},
        prices={"input": 4.0, "output": 20.0, "cache_read": 0.40, "cache_write": None},
        price_verified=False,
        price_source=("global online-prediction SKU as reported for the Cloud catalog ($4/$20); Google announced an "
                      "introductory $2/$10. Cache read assumed at 10% of input. Confirm on the Agent Platform "
                      "pricing page before any scored run."),
        opencode_npm="@ai-sdk/google", opencode_model="gemini-4-carbon",
        notes=("Returns rolling thought summaries, not full thinking: trace thinking.kind is 'summary' or 'omitted'.",),
    ),
    "claude-opus-5-5": VertexModel(
        key="claude-opus-5-5", display="Claude Opus 5.5", vertex_id="claude-opus-5-5", publisher="anthropic",
        location="global", wire="anthropic", client_ids=("claude-opus-5-5",),
        thinking={"type": "adaptive"},
        prices={"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0},
        price_verified=True, price_source="thesis/ab/vertex_list_prices.json (Standard, global, read 2026-10-29)",
        opencode_npm="@ai-sdk/anthropic", opencode_model="claude-opus-5-5",
        notes=("Regional endpoints serve Sonnet 4.6 and earlier only; Opus 5.5 is global or the us/eu multi-region.",),
    ),
    "gpt-oss-120b": VertexModel(
        key="gpt-oss-120b", display="gpt-oss 120B", vertex_id="gpt-oss-120b-maas", publisher="openai",
        location="global", wire="openai_chat", client_ids=("gpt-oss-120b-maas", "openai/gpt-oss-120b-maas"),
        thinking={"reasoning_effort": "high"},
        prices={"input": 0.15, "output": 0.60, "cache_read": None, "cache_write": None},
        price_verified=False,
        price_source=("GA announcement rate ($0.15/$0.60); current aggregators list $0.09/$0.36. Confirm on the "
                      "Agent Platform pricing page before any scored run."),
        opencode_npm="@ai-sdk/openai-compatible", opencode_model="gpt-oss-120b-maas",
        notes=("Vertex's model page lists 'Thinking: Not supported', yet the endpoint accepts reasoning_effort and "
               "returns reasoning_content; usage reasoning_tokens has been reported as 0 even at high effort. "
               "Thinking tokens are still read from usage (never estimated from text).",),
    ),
}

def count_o200k_harmony(text: str) -> tuple[int | None, str]:
    """Our own token count of gpt-oss reasoning text with the ``o200k_harmony``
    encoding (tiktoken). Recorded as ``thinking.tokens_counted``, separate from
    and never pooled with the usage value. Optional: no tiktoken, no count."""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("o200k_harmony")
    except (ImportError, ValueError, KeyError) as exc:
        return None, f"unavailable: {type(exc).__name__}: {exc}"
    return len(encoding.encode(text, disallowed_special=())), "computed: tiktoken o200k_harmony (not provider usage)"


def served_matches(model: VertexModel, served) -> bool:
    """True when the served model Vertex reports is this model. Vertex reports
    gpt-oss in its publisher/model body form (``openai/gpt-oss-120b-maas``)."""
    accepted = (model.vertex_id, OPENAI_BODY_MODEL.get(model.key) or model.vertex_id)
    return isinstance(served, str) and any(served.startswith(a) for a in accepted)


# Models whose usage thinking-token count can't be compared with the others'.
# gpt-oss on Vertex reports 0 even when it returns reasoning text, so its
# thinking is evidenced by the text (chars, optional counted tokens) instead.
THINKING_TOKENS_FROM_TEXT = {"gpt-oss-120b": count_o200k_harmony}

# Body model sent upstream for the OpenAI-compatible endpoint (publisher/model).
OPENAI_BODY_MODEL = {"gpt-oss-120b": "openai/gpt-oss-120b-maas"}


def resolve(name: str) -> VertexModel:
    """The registered model named exactly ``name``. No aliases, no defaults,
    no fallback to another model or provider."""
    if not isinstance(name, str) or not name.strip():
        raise UnknownModel("no model given; the reflection loop needs one of " + ", ".join(MODELS))
    if any(bad in name.lower() for bad in FORBIDDEN_SUBSTRINGS):
        raise UnknownModel(f"{name!r}: Sonnet and Qwen are not reflection-loop models")
    try:
        return MODELS[name]
    except KeyError:
        raise UnknownModel(f"{name!r} is not a reflection-loop model; use one of {', '.join(MODELS)}") from None


def provider_id(model: VertexModel) -> str:
    return f"vertex-{model.key}"


def opencode_model_arg(model: VertexModel) -> str:
    """``--model`` for OpenCode: ``<provider>/<model id>``."""
    return f"{provider_id(model)}/{model.opencode_model}"


def opencode_config(model: VertexModel, proxy_base: str) -> dict:
    """``OPENCODE_CONFIG_CONTENT`` for one model: a single provider pointed
    at the recording proxy route, ``enabled_providers`` limited to it (no
    other provider can load), and ``small_model`` on the same model so side
    calls (titles) stay on it."""
    pid = provider_id(model)
    base = proxy_base.rstrip("/") + f"/m/{model.key}"
    base += {"anthropic": "/v1", "gemini": "/v1beta", "openai_chat": "/v1"}[model.wire]
    entry = {"name": model.display, "reasoning": True, "tool_call": True,
             "limit": {"context": 200000, "output": 32000}}
    if model.wire == "openai_chat":
        entry["interleaved"] = {"field": "reasoning_content"}
    return {
        "$schema": "https://opencode.ai/config.json",
        "enabled_providers": [pid],
        "model": opencode_model_arg(model),
        "small_model": opencode_model_arg(model),
        "share": "disabled",
        "autoupdate": False,
        "provider": {pid: {"npm": model.opencode_npm, "name": model.display,
                           "options": {"baseURL": base, "apiKey": "openbench-proxy"},
                           "models": {model.opencode_model: entry}}},
    }


def opencode_config_env(model: VertexModel, proxy_base: str) -> str:
    return json.dumps(opencode_config(model, proxy_base), sort_keys=True)


def cost_usd(model: VertexModel, usage: dict) -> float | None:
    """USD for one call from normalized usage (``trace.usage_from_response``).
    Thinking is billed as output. Gemini's ``promptTokenCount`` includes
    cached tokens and its ``candidatesTokenCount`` excludes thinking, so both
    are adjusted. None when a needed rate is missing."""
    p = model.prices
    inp, out = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
    read, write = usage.get("cache_read_tokens") or 0, usage.get("cache_write_tokens") or 0
    thinking = usage.get("thinking_tokens") or 0
    if model.wire == "gemini":
        inp, out = max(inp - read, 0), out + thinking
    elif model.wire == "openai_chat":
        inp = max(inp - read, 0)
    total = inp * p["input"] + out * p["output"]
    for tokens, rate in ((read, p["cache_read"]), (write, p["cache_write"])):
        if tokens:
            if rate is None:
                return None
            total += tokens * rate
    return round(total / 1_000_000, 8)
