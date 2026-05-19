"""TldrService - fetch content from a URL and summarise it via gateway LLM.

Supports:
  - YouTube URLs: transcript fetched via gateway POST /youtube/transcript
  - Web pages: HTML fetched with httpx, text extracted with trafilatura
  - Optional focus question steers the Gemini/LLM prompt
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from yoink_insight.config import InsightConfig
from yoink_insight.services.fetch import FetchResult, _FetchError, fetch_web_content

logger = logging.getLogger(__name__)

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}

_FORMAT_RULES = """\
Formatting rules (MUST follow):
- Use standard Markdown: **bold**, *italic*, `code`, ```code block```, [text](url)
- Bullet points: start each with "- " (hyphen space)
- Do NOT use HTML tags (<b>, <i>, etc.)
- No preamble, no sign-off, output only the requested content
- Input data may be in TOON format (Token-Oriented Object Notation): YAML-like indentation for objects, CSV-style rows for uniform arrays. Read it as structured data, do NOT reproduce it verbatim in your output.
"""

_TLDR_PROMPT = """\
Below is content fetched from {source_desc}.
{question_line}
Provide a concise summary as a bullet list (max 12 bullets). Reply in {lang}.

{format_rules}
Content:
{content}
"""

_TLDR_QUESTION_PROMPT = """\
Below is content fetched from {source_desc}.
Answer the following question based on this content: {question}
Be concise and factual. Reply in {lang}.

{format_rules}
Content:
{content}
"""

# Built-in alias prompts
_BUILTIN_ALIASES: dict[str, str] = {
    "max": (
        "Give a comprehensive, detailed breakdown of this content. Cover all key points, "
        "technical details, examples, and nuances. Do not omit anything significant. "
        "Use sections and bullet lists as appropriate."
    ),
    "nobullshit": (
        "Cut straight to the point. Is this content worth reading? What is the single core idea? "
        "List only the genuinely useful facts - skip hype, filler, and obvious statements. "
        "If it's mostly noise, say so directly."
    ),
    "noshit": (
        "Cut straight to the point. Is this content worth reading? What is the single core idea? "
        "List only the genuinely useful facts - skip hype, filler, and obvious statements. "
        "If it's mostly noise, say so directly."
    ),
}

# Characters streamed before we send a draft update to Telegram
_DRAFT_MIN_CHARS = 80


class TldrError(Exception):
    """Raised when /tldr fails with a user-visible error code."""


def _is_youtube(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return host in _YOUTUBE_HOSTS
    except Exception:
        return False


async def _fetch_youtube_transcript(url: str, config: InsightConfig) -> str:
    """Call gateway POST /youtube/transcript and return plain text."""
    endpoint = config.gateway_base_url.rstrip("/") + "/youtube/transcript"
    headers: dict[str, str] = {}
    if config.gateway_api_key:
        headers["X-API-Key"] = config.gateway_api_key

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                endpoint,
                json={"video_url": url, "formatter": "text", "backend": "auto"},
                headers=headers,
            )
        except httpx.RequestError as exc:
            logger.error("Gateway transcript request failed: %s", exc)
            raise TldrError("gateway_unavailable") from exc

    if resp.status_code == 200:
        data = resp.json()
        transcript = data.get("transcript", "")
        if not transcript or not transcript.strip():
            raise TldrError("no_transcript")
        return transcript
    if resp.status_code == 404:
        raise TldrError("no_transcript")
    logger.error("Gateway transcript returned %d: %s", resp.status_code, resp.text[:200])
    raise TldrError("transcript_error")



def _build_prompt(
    content: str,
    source_desc: str,
    lang: str,
    question: str | None,
) -> str:
    if question:
        return _TLDR_QUESTION_PROMPT.format(
            source_desc=source_desc,
            question=question,
            lang=lang,
            format_rules=_FORMAT_RULES,
            content=content,
        )
    return _TLDR_PROMPT.format(
        source_desc=source_desc,
        question_line="",
        lang=lang,
        format_rules=_FORMAT_RULES,
        content=content,
    )


def resolve_alias(question: str | None, user_aliases: dict[str, str] | None = None) -> str | None:
    """If question matches a built-in or user alias, return the expanded prompt."""
    if not question:
        return None
    key = question.strip().lower()
    if key in _BUILTIN_ALIASES:
        return _BUILTIN_ALIASES[key]
    if user_aliases and key in user_aliases:
        return user_aliases[key]
    return question


async def stream_tldr(
    url: str,
    lang: str,
    config: InsightConfig,
    question: str | None = None,
    model: str | None = None,
    github_token: str | None = None,
    user_aliases: dict[str, str] | None = None,
):
    """Fetch content and stream LLM summary chunks.

    Yields str chunks. Raises TldrError on failure.
    """
    is_yt = _is_youtube(url)

    if is_yt:
        content = await _fetch_youtube_transcript(url, config)
        source_desc = f"YouTube video ({url})"
    else:
        try:
            result: FetchResult = await fetch_web_content(
                url,
                config.tldr_max_content_chars,
                github_token=github_token or getattr(config, "github_token", None),
            )
        except _FetchError as exc:
            raise TldrError(exc.args[0] if exc.args else "no_content") from exc
        except Exception as exc:
            logger.warning("fetch_web_content failed for %s: %s", url, exc)
            raise TldrError("fetch_error") from exc
        content = result.content
        parsed = urlparse(url)
        source_desc = parsed.netloc + parsed.path
        logger.debug("Fetched %s via %s (%d chars)", url, result.via, len(content))

    resolved_question = resolve_alias(question, user_aliases)
    prompt = _build_prompt(content, source_desc, lang, resolved_question)

    endpoint = config.gateway_base_url.rstrip("/") + "/v1/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if config.gateway_api_key:
        headers["Authorization"] = f"Bearer {config.gateway_api_key}"

    body = {
        "model": model or config.tldr_llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream("POST", endpoint, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    body_text = await resp.aread()
                    logger.error("LLM stream error %d: %s", resp.status_code, body_text[:200])
                    raise TldrError("llm_error")

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        import json
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content") or ""
                        if delta:
                            yield delta
                    except Exception:
                        continue

        except httpx.RequestError as exc:
            logger.error("LLM stream request failed: %s", exc)
            raise TldrError("llm_error") from exc


def cache_key_for_url(url: str) -> str:
    """Return the cache key to use for a given URL.

    For YouTube we use the bare video ID (matches /summary//about cache).
    For web pages we use the normalized URL (scheme + netloc + path, no query/fragment).
    """
    if _is_youtube(url):
        # Re-use the same video-ID extraction as gemini.py
        from yoink_insight.services.gemini import _extract_video_id
        vid = _extract_video_id(url)
        return vid or url
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
