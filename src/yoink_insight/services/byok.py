"""Bring-Your-Own-Key provider clients for /tldr.

Six providers + an Anthropic-native shape:
  openai            (OpenAI Chat Completions, /v1/models)
  anthropic         (Anthropic Messages API, hardcoded model list)
  gemini            (Google Gemini OpenAI-compat at /v1beta/openai)
  openrouter        (OpenAI Chat Completions, rich /v1/models)
  perplexity        (OpenAI Chat Completions, hardcoded sonar* list)
  custom_openai     (user URL, OpenAI shape)
  custom_anthropic  (user URL, Anthropic shape)

Each provider is described by a ProviderSpec with default base_url,
auth header layout, model-list strategy, and a websearch capability check.

The public surface:
  - PROVIDERS: dict[str, ProviderSpec]
  - resolve_base_url(provider, override) -> str
  - probe(provider, base_url, key) -> ProbeResult
  - list_models(provider, base_url, key) -> list[ModelInfo]
  - has_websearch(provider, model_id) -> bool
  - stream_chat(provider, base_url, key, model, prompt) -> AsyncIterator[str]
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    default_base_url: str | None      # None -> URL is required from the user
    api_shape: str                    # 'openai' | 'anthropic'
    # Whether to attempt GET /v1/models (or equivalent) for live model list.
    supports_models_endpoint: bool
    # Fallback model ids when /v1/models is unavailable or fails.
    fallback_models: tuple[str, ...] = ()
    # When True, every model from this provider is treated as websearch-capable.
    all_websearch: bool = False


# Hardcoded fallback lists for providers that don't expose /v1/models or where
# we want a curated default.
_ANTHROPIC_FALLBACK = (
    "claude-opus-4-1-20250805",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
    "claude-3-7-sonnet-latest",
    "claude-3-5-haiku-latest",
)

_PERPLEXITY_FALLBACK = (
    "sonar",
    "sonar-pro",
    "sonar-reasoning",
    "sonar-reasoning-pro",
    "sonar-deep-research",
)

_OPENAI_FALLBACK = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4o-mini-search-preview",
    "gpt-4o-search-preview",
)

_GEMINI_FALLBACK = (
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
)


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        id="openai",
        label="OpenAI",
        default_base_url="https://api.openai.com/v1",
        api_shape="openai",
        supports_models_endpoint=True,
        fallback_models=_OPENAI_FALLBACK,
    ),
    "anthropic": ProviderSpec(
        id="anthropic",
        label="Anthropic",
        default_base_url="https://api.anthropic.com",
        api_shape="anthropic",
        supports_models_endpoint=True,
        fallback_models=_ANTHROPIC_FALLBACK,
    ),
    "gemini": ProviderSpec(
        id="gemini",
        label="Google Gemini",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_shape="openai",
        supports_models_endpoint=True,
        fallback_models=_GEMINI_FALLBACK,
    ),
    "openrouter": ProviderSpec(
        id="openrouter",
        label="OpenRouter",
        default_base_url="https://openrouter.ai/api/v1",
        api_shape="openai",
        supports_models_endpoint=True,
        fallback_models=(),
    ),
    "perplexity": ProviderSpec(
        id="perplexity",
        label="Perplexity",
        default_base_url="https://api.perplexity.ai",
        api_shape="openai",
        supports_models_endpoint=False,
        fallback_models=_PERPLEXITY_FALLBACK,
        all_websearch=True,
    ),
    "custom_openai": ProviderSpec(
        id="custom_openai",
        label="Custom (OpenAI-compatible)",
        default_base_url=None,
        api_shape="openai",
        supports_models_endpoint=True,
        fallback_models=(),
    ),
    "custom_anthropic": ProviderSpec(
        id="custom_anthropic",
        label="Custom (Anthropic-compatible)",
        default_base_url=None,
        api_shape="anthropic",
        supports_models_endpoint=True,
        fallback_models=_ANTHROPIC_FALLBACK,
    ),
}


# ---------------------------------------------------------------------------
# Model + probe value objects
# ---------------------------------------------------------------------------


@dataclass
class ModelInfo:
    id: str
    supports_websearch: bool


@dataclass
class ProbeResult:
    ok: bool
    error: str | None = None
    models: list[ModelInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Websearch capability
# ---------------------------------------------------------------------------

# Model-id substrings that mark a websearch-capable model regardless of
# provider. Matched against the lowercased model id.
_WEBSEARCH_HARDCODED_PATTERNS = (
    re.compile(r"^sonar"),                       # perplexity sonar*
    re.compile(r":online$"),                     # openrouter *:online
    re.compile(r"-search-preview"),              # openai gpt-4o*-search-preview
    re.compile(r"^perplexity/"),                 # openrouter perplexity/*
    re.compile(r"-online$"),                     # rare legacy variant
)


def has_websearch(provider: str, model_id: str) -> bool:
    spec = PROVIDERS.get(provider)
    if spec is not None and spec.all_websearch:
        return True
    mid = (model_id or "").lower()
    return any(p.search(mid) for p in _WEBSEARCH_HARDCODED_PATTERNS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class BYOKError(Exception):
    """Raised when a BYOK probe / stream fails. Code is exc.args[0]."""


def resolve_base_url(provider: str, override: str | None) -> str:
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise BYOKError(f"unknown_provider:{provider}")
    base = (override or "").strip().rstrip("/")
    if base:
        return base
    if spec.default_base_url is None:
        raise BYOKError("base_url_required")
    return spec.default_base_url


def _openai_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _anthropic_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }


def _annotate_models(provider: str, ids: list[str]) -> list[ModelInfo]:
    return [ModelInfo(id=mid, supports_websearch=has_websearch(provider, mid)) for mid in ids]


# ---------------------------------------------------------------------------
# Model list fetch
# ---------------------------------------------------------------------------


async def list_models(provider: str, base_url: str, api_key: str) -> list[ModelInfo]:
    """Fetch the provider model catalogue, falling back to the hardcoded list.

    Never raises - returns the fallback on any network or auth error so the
    UI can still show *something*.
    """
    spec = PROVIDERS.get(provider)
    if spec is None:
        return []

    if spec.supports_models_endpoint:
        try:
            if spec.api_shape == "openai":
                ids = await _fetch_openai_models(base_url, api_key)
            else:
                ids = await _fetch_anthropic_models(base_url, api_key)
            if ids:
                return _annotate_models(provider, ids)
        except Exception as exc:
            logger.info("byok list_models(%s) live fetch failed: %s", provider, exc)

    return _annotate_models(provider, list(spec.fallback_models))


async def _fetch_openai_models(base_url: str, api_key: str) -> list[str]:
    endpoint = base_url.rstrip("/") + "/models"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(endpoint, headers=_openai_headers(api_key))
    if resp.status_code != 200:
        raise BYOKError(f"http_{resp.status_code}")
    data = resp.json().get("data", [])
    return [m.get("id") for m in data if m.get("id")]


async def _fetch_anthropic_models(base_url: str, api_key: str) -> list[str]:
    endpoint = base_url.rstrip("/") + "/v1/models"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(endpoint, headers=_anthropic_headers(api_key))
    if resp.status_code != 200:
        raise BYOKError(f"http_{resp.status_code}")
    data = resp.json().get("data", [])
    return [m.get("id") for m in data if m.get("id")]


# ---------------------------------------------------------------------------
# Probe (used by /byok/me/test)
# ---------------------------------------------------------------------------


async def probe(provider: str, base_url: str | None, api_key: str) -> ProbeResult:
    """Smoke-test the key+endpoint. Returns models on success."""
    if not api_key or not api_key.strip():
        return ProbeResult(ok=False, error="api_key_required")
    try:
        base = resolve_base_url(provider, base_url)
    except BYOKError as exc:
        return ProbeResult(ok=False, error=exc.args[0] if exc.args else "bad_base_url")

    spec = PROVIDERS[provider]
    try:
        if spec.supports_models_endpoint:
            if spec.api_shape == "openai":
                ids = await _fetch_openai_models(base, api_key)
            else:
                ids = await _fetch_anthropic_models(base, api_key)
            return ProbeResult(ok=True, models=_annotate_models(provider, ids or list(spec.fallback_models)))

        # Providers without /v1/models: run a tiny chat probe to verify auth.
        await _ping_chat(spec, base, api_key)
        return ProbeResult(ok=True, models=_annotate_models(provider, list(spec.fallback_models)))
    except httpx.ConnectError:
        return ProbeResult(ok=False, error="connect_error")
    except httpx.TimeoutException:
        return ProbeResult(ok=False, error="timeout")
    except BYOKError as exc:
        return ProbeResult(ok=False, error=exc.args[0] if exc.args else "probe_failed")
    except Exception as exc:
        logger.warning("byok probe(%s) unexpected: %s", provider, exc)
        return ProbeResult(ok=False, error="probe_failed")


async def _ping_chat(spec: ProviderSpec, base_url: str, api_key: str) -> None:
    """Cheap auth probe for providers without /v1/models (perplexity)."""
    model = spec.fallback_models[0] if spec.fallback_models else ""
    if not model:
        return
    if spec.api_shape == "openai":
        endpoint = base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }
        headers = _openai_headers(api_key)
    else:
        endpoint = base_url.rstrip("/") + "/v1/messages"
        body = {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }
        headers = _anthropic_headers(api_key)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(endpoint, headers=headers, json=body)
    if resp.status_code == 401 or resp.status_code == 403:
        raise BYOKError("auth_failed")
    if resp.status_code >= 500:
        raise BYOKError(f"http_{resp.status_code}")
    # 400 with "max_tokens too low" or similar still proves auth works.


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------


async def stream_chat(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
) -> AsyncIterator[str]:
    """Stream LLM completion chunks for a single-user-message prompt.

    Yields plain text deltas. Raises BYOKError on transport / API failure.
    """
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise BYOKError(f"unknown_provider:{provider}")

    if spec.api_shape == "openai":
        async for chunk in _stream_openai(base_url, api_key, model, prompt):
            yield chunk
    else:
        async for chunk in _stream_anthropic(base_url, api_key, model, prompt):
            yield chunk


def _extract_provider_message(raw: bytes) -> str:
    """Pull the human-readable error from an OpenAI/OpenRouter/Anthropic JSON body.

    Falls back to the truncated raw bytes when the payload is not JSON or has
    no recognisable `error.message` field.
    """
    snippet = raw[:400]
    try:
        payload = json.loads(snippet)
    except Exception:
        return snippet.decode("utf-8", errors="replace")
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        msg = err.get("message")
        if isinstance(msg, str) and msg:
            return msg
    if isinstance(err, str) and err:
        return err
    return snippet.decode("utf-8", errors="replace")


def _classify_provider_status(status: int) -> str:
    """Map an upstream HTTP status onto a stable BYOKError code."""
    if status in (401, 403):
        return "auth_failed"
    if status == 402:
        return "insufficient_credits"
    if status == 429:
        return "provider_rate_limited"
    if status == 404:
        return "model_not_found"
    if status >= 500:
        return "provider_unavailable"
    return "llm_error"


async def _stream_openai(
    base_url: str, api_key: str, model: str, prompt: str
) -> AsyncIterator[str]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream("POST", endpoint, json=body, headers=_openai_headers(api_key)) as resp:
                if resp.status_code != 200:
                    raw = await resp.aread()
                    message = _extract_provider_message(raw)
                    code = _classify_provider_status(resp.status_code)
                    logger.error(
                        "byok openai stream %d (%s): %s", resp.status_code, code, message
                    )
                    raise BYOKError(code)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content") or ""
                        if delta:
                            yield delta
                    except Exception:
                        continue
        except httpx.RequestError as exc:
            logger.error(
                "byok openai stream request failed (%s): %s",
                type(exc).__name__,
                exc or "connection closed",
            )
            raise BYOKError("network_error") from exc


async def _stream_anthropic(
    base_url: str, api_key: str, model: str, prompt: str
) -> AsyncIterator[str]:
    """Stream Anthropic Messages API SSE, emit content deltas as plain strings.

    Event sequence: message_start -> content_block_start -> content_block_delta*
    -> content_block_stop -> message_delta -> message_stop. We only forward
    text deltas from content_block_delta events of type 'text_delta'.
    """
    endpoint = base_url.rstrip("/") + "/v1/messages"
    body = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    headers = _anthropic_headers(api_key)
    headers["accept"] = "text/event-stream"

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream("POST", endpoint, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    raw = await resp.aread()
                    message = _extract_provider_message(raw)
                    code = _classify_provider_status(resp.status_code)
                    logger.error(
                        "byok anthropic stream %d (%s): %s", resp.status_code, code, message
                    )
                    raise BYOKError(code)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        evt = json.loads(data)
                    except Exception:
                        continue
                    if evt.get("type") != "content_block_delta":
                        continue
                    delta = evt.get("delta") or {}
                    if delta.get("type") != "text_delta":
                        continue
                    text = delta.get("text") or ""
                    if text:
                        yield text
        except httpx.RequestError as exc:
            logger.error(
                "byok anthropic stream request failed (%s): %s",
                type(exc).__name__,
                exc or "connection closed",
            )
            raise BYOKError("network_error") from exc


# ---------------------------------------------------------------------------
# Catalogue snapshot for the UI
# ---------------------------------------------------------------------------


def provider_catalogue() -> list[dict]:
    """Return a JSON-friendly description of every provider for the UI."""
    return [
        {
            "id": s.id,
            "label": s.label,
            "default_base_url": s.default_base_url,
            "requires_base_url": s.default_base_url is None,
            "api_shape": s.api_shape,
            "all_websearch": s.all_websearch,
        }
        for s in PROVIDERS.values()
    ]
