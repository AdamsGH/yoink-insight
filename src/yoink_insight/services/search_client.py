"""Client for the gateway answer engine (POST /v1/search).

Used as an optional fetch override for /tldr, /summary, /about. The gateway
runs classifier -> researcher -> rerank and returns ranked sources. We ask for
``mode='raw'`` (no writer answer) and ``format='toon'`` (compact tabular
encoding) and feed the joined source content into our own LLM summariser
prompt - the writer answer the gateway would produce is discarded.

This lets us reuse the gateway's richer fetch stack (search engine fallback,
StackOverflow / GitHub / Reddit integrations, smart scrape + rerank) while
keeping the final summary format under our control.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from yoink_insight.config import InsightConfig

logger = logging.getLogger(__name__)


@dataclass
class SearchSource:
    url: str
    title: str
    snippet: str
    content: str
    score: float
    engine: str


@dataclass
class SearchFetchResult:
    sources: list[SearchSource]
    via: str  # e.g. "gateway-search:answer" or "gateway-search:raw"


class SearchFetchError(Exception):
    """Raised when /v1/search fails or returns no usable sources."""


def _decode_toon(text: str) -> dict:
    """Decode a TOON-encoded response into a dict."""
    from toon_format import decode  # local import: optional dep at runtime
    return decode(text)


async def search_fetch(
    query: str,
    config: InsightConfig,
    *,
    optimization: str = "balanced",
    top_k: int = 5,
    max_content_chars: int | None = None,
) -> SearchFetchResult:
    """Run /v1/search in raw mode and return ranked sources.

    query: either a plain question ('how does cross-entropy work') or a URL.
    The gateway classifier figures out whether to run a research loop or
    just scrape the single URL.

    Raises SearchFetchError on transport failure, non-200 response, or empty
    source list. Caller is expected to fall back to the legacy fetch path.
    """
    endpoint = config.gateway_base_url.rstrip("/") + "/v1/search"
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/toon",
    }
    if config.gateway_api_key:
        headers["Authorization"] = f"Bearer {config.gateway_api_key}"

    body = {
        "query": query,
        "mode": "raw",
        "optimization": optimization,
        "format": "toon",
        # For bare-URL inputs the classifier still gates research; force_search
        # ensures we always reach the scrape stage even when it tags the input
        # as 'skip search' (common false-positive for unfamiliar domains).
        "force_search": True,
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(endpoint, json=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning("gateway /v1/search request failed: %s", exc)
        raise SearchFetchError("gateway_unavailable") from exc

    if resp.status_code != 200:
        logger.warning("gateway /v1/search returned %d: %s", resp.status_code, resp.text[:200])
        raise SearchFetchError("search_error")

    try:
        decoded = _decode_toon(resp.text)
    except Exception as exc:
        logger.warning("gateway /v1/search TOON decode failed: %s", exc)
        raise SearchFetchError("search_error") from exc

    raw_sources = decoded.get("sources") or []
    sources: list[SearchSource] = []
    for item in raw_sources[:top_k]:
        content = item.get("content") or ""
        if max_content_chars and len(content) > max_content_chars:
            content = content[:max_content_chars] + "\n\n[Content truncated]"
        sources.append(SearchSource(
            url=item.get("url", ""),
            title=item.get("title", ""),
            snippet=item.get("snippet", ""),
            content=content,
            score=float(item.get("score", 0.0)),
            engine=item.get("engine", ""),
        ))

    if not sources or all(not s.content.strip() for s in sources):
        raise SearchFetchError("no_content")

    return SearchFetchResult(sources=sources, via="gateway-search:raw")


def join_sources_for_llm(sources: list[SearchSource]) -> str:
    """Concatenate ranked sources into a single content blob for our summariser.

    Each source is wrapped with a short header so the LLM knows what page
    each block came from. Empty-content sources are skipped (their title +
    snippet alone do not give the summariser anything to chew on).
    """
    blocks: list[str] = []
    for i, src in enumerate(sources, 1):
        if not src.content.strip():
            continue
        header = f"### Source {i}: {src.title or src.url}\nURL: {src.url}\n"
        blocks.append(header + "\n" + src.content.strip())
    return "\n\n---\n\n".join(blocks)
