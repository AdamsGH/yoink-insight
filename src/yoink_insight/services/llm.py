"""Public LLM completion helper for other plugins.

This is the stable surface other plugins should depend on instead of
re-implementing BYOK + gateway routing. It hides:

- BYOK detection (insight_user_byok row, tested, no error -> direct provider)
- Gateway routing (POST /v1/chat/completions on `InsightConfig.gateway_base_url`)
- Provider error normalisation (InboxLlmError analogue lives here as
  `LlmCompletionError` with stable codes)

For TLDR-specific streaming + prompt-construction the legacy
`yoink_insight.services.tldr.stream_llm` is still the right entry point.
For \"give me a prompt completion, return a string\" use `complete()`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from yoink_insight.config import InsightConfig
from yoink_insight.services.byok import (
    BYOKError,
    resolve_base_url,
    stream_chat as byok_stream_chat,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class LlmCompletionError(RuntimeError):
    """Stable error codes:

    - `no_route`: no BYOK row AND no gateway base url configured
    - `auth_failed`: 401/403 from upstream
    - `insufficient_credits`: 402
    - `provider_rate_limited`: 429
    - `model_not_found`: 404
    - `provider_unavailable`: 5xx or transport failure
    - `llm_error`: any other 4xx
    - `parse_failed`: gateway returned a body we cannot read
    """


@dataclass(frozen=True, slots=True)
class _Route:
    """Resolved LLM route. Either a BYOK direct call or the gateway."""

    via_byok: bool
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


async def resolve_route(
    session_factory: "async_sessionmaker",
    user_id: int,
    *,
    prefer_byok: bool = True,
) -> _Route:
    """Pick a route for `user_id`.

    BYOK wins when present and tested-clean; this matches `tldr.stream_llm`
    semantics (user's own provider is the user's authority). Set
    `prefer_byok=False` to skip the BYOK check and always go through the
    gateway (used by admin / system-wide jobs).
    """
    if prefer_byok:
        from yoink_insight.storage.repos import InsightUserByokRepo

        repo = InsightUserByokRepo(session_factory)
        row = await repo.get(user_id)
        if row is not None and row.tested_at is not None and not row.test_error:
            return _Route(
                via_byok=True,
                provider=row.provider,
                base_url=row.base_url,
                api_key=row.api_key,
                model=row.model,
            )

    cfg = InsightConfig()
    base = cfg.gateway_base_url.rstrip("/")
    if not base:
        raise LlmCompletionError("no_route")
    return _Route(via_byok=False, model=cfg.tldr_llm_model)


async def complete(
    session_factory: "async_sessionmaker",
    user_id: int,
    prompt: str,
    *,
    model: str | None = None,
    timeout_s: float = 120.0,
    prefer_byok: bool = True,
) -> str:
    """Run `prompt` through the user's route and return the buffered completion.

    `model` only affects the gateway path; BYOK rows already pin a model.
    Raises `LlmCompletionError` with a stable code on any failure.
    """
    route = await resolve_route(session_factory, user_id, prefer_byok=prefer_byok)
    if route.via_byok:
        return await _run_byok(route, prompt)
    return await _run_gateway(prompt, override_model=model, timeout_s=timeout_s)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


async def _run_byok(route: _Route, prompt: str) -> str:
    assert route.provider and route.api_key and route.model, "BYOK route incomplete"
    try:
        base = resolve_base_url(route.provider, route.base_url)
    except BYOKError as exc:
        logger.error("llm.complete BYOK base url resolution failed: %s", exc)
        raise LlmCompletionError("llm_error") from exc

    buf: list[str] = []
    try:
        async for chunk in byok_stream_chat(
            route.provider, base, route.api_key, route.model, prompt,
        ):
            buf.append(chunk)
    except BYOKError as exc:
        code = exc.args[0] if exc.args else "llm_error"
        raise LlmCompletionError(code) from exc
    return "".join(buf)


async def _run_gateway(
    prompt: str, *, override_model: str | None, timeout_s: float,
) -> str:
    cfg = InsightConfig()
    base = cfg.gateway_base_url.rstrip("/")
    endpoint = f"{base}/v1/chat/completions"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg.gateway_api_key:
        headers["Authorization"] = f"Bearer {cfg.gateway_api_key}"

    body = {
        "model": override_model or cfg.tldr_llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(endpoint, json=body, headers=headers)
    except httpx.HTTPError as exc:
        logger.error("llm.complete gateway transport failed: %r", exc)
        raise LlmCompletionError("provider_unavailable") from exc

    if r.status_code in (401, 403):
        raise LlmCompletionError("auth_failed")
    if r.status_code == 402:
        raise LlmCompletionError("insufficient_credits")
    if r.status_code == 404:
        raise LlmCompletionError("model_not_found")
    if r.status_code == 429:
        raise LlmCompletionError("provider_rate_limited")
    if r.status_code >= 500:
        raise LlmCompletionError("provider_unavailable")
    if r.status_code >= 400:
        logger.error("llm.complete gateway %d: %s", r.status_code, r.text[:200])
        raise LlmCompletionError("llm_error")

    try:
        payload = r.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise LlmCompletionError("parse_failed") from exc

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmCompletionError("parse_failed") from exc

    return content or ""
