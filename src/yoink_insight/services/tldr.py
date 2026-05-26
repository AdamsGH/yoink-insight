"""TldrService - fetch content from a URL and summarise it via gateway LLM.

Supports:
  - YouTube URLs: transcript fetched via gateway POST /youtube/transcript
  - Web pages: HTML fetched with httpx, text extracted with trafilatura
  - Optional focus question steers the Gemini/LLM prompt
"""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from yoink_insight.config import InsightConfig
from yoink_insight.services.byok import BYOKError, resolve_base_url, stream_chat as byok_stream_chat
from yoink_insight.services.fetch import FetchResult, _FetchError, fetch_web_content
from yoink_insight.services.search_client import SearchFetchError, join_sources_for_llm, search_fetch

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

# Default built-in /tldr instruction. This is the body the user can override
# via insight_user_prompts(command='tldr'). It is rendered with {lang} only;
# the source/content/format-rules block is appended automatically below.
TLDR_INSTRUCTION = """\
You are summarising content the user dropped into a chat - a web article,
repo page, or video transcript. Produce a tight, specific bullet list
(maximum 12 bullets) that captures the actual ideas, claims, and
conclusions present in the source.

Rules:
- Each bullet must carry a concrete fact, claim, code reference, or
  recommendation. Skip filler like "the post discusses X".
- Preserve names, versions, model identifiers, paths, and error tokens
  verbatim. Numbers stay as numbers.
- Lead with the most important point first, then descend by relevance.
- Do NOT recap the structure of the source ("the author first introduces,
  then explains"). State the actual point.
- If the source contradicts itself or contains hype without evidence,
  note that explicitly in a bullet.
- No preamble, no closing summary, no sign-off. Output only the bullets.
- Reply in {lang}.
"""

_TLDR_BODY = """\
Below is content fetched from {source_desc}.

{format_rules}
Content:
{content}
"""

_TLDR_QUESTION_BODY = """\
Below is content fetched from {source_desc}.
Answer the following question based on this content: {question}
Be direct and specific. Reply in {lang}.

{format_rules}
Content:
{content}
"""

# Built-in alias prompts
_BUILTIN_ALIASES: dict[str, str] = {
    "max": (
        "Give a thorough, well-structured breakdown of this content. "
        "Cover all significant points, technical details, examples, and nuances in depth. "
        "Do not omit anything meaningful. Use sections with bold headings and bullet lists."
    ),
    "nobullshit": (
        "You are a cynical, no-nonsense critic. Be blunt and direct - do not soften your verdict. "
        "Start with a one-line verdict: is this worth reading, or is it a waste of time? Be specific. "
        "Then list ONLY the genuinely new or useful facts - maximum 7 bullets, each one a concrete claim. "
        "If a bullet would not survive the question 'so what?' - cut it. "
        "Call out hype, padding, and obvious statements explicitly if they dominate the content. "
        "Do NOT summarise structure or intentions ('the author explains...') - summarise actual content. "
        "Reply in {lang}."
    ),
    "noshit": (
        "You are a cynical, no-nonsense critic. Be blunt and direct - do not soften your verdict. "
        "Start with a one-line verdict: is this worth reading, or is it a waste of time? Be specific. "
        "Then list ONLY the genuinely new or useful facts - maximum 7 bullets, each one a concrete claim. "
        "If a bullet would not survive the question 'so what?' - cut it. "
        "Call out hype, padding, and obvious statements explicitly if they dominate the content. "
        "Do NOT summarise structure or intentions ('the author explains...') - summarise actual content. "
        "Reply in {lang}."
    ),
}

# i18n key suffix for the Telegram message header per alias
_BUILTIN_ALIAS_HEADER_KEY: dict[str, str] = {
    "nobullshit": "tldr.header_nobullshit",
    "noshit": "tldr.header_nobullshit",
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


async def _fetch_youtube_transcript(url: str, config: InsightConfig) -> tuple[str, int | None]:
    """Call gateway POST /youtube/transcript and return (transcript, duration_seconds).

    duration_seconds is None when the gateway could not determine the length
    (very old gateway without include_duration support, or all probes failed).
    The caller is expected to fall back to a word-count heuristic in that case.
    """
    endpoint = config.gateway_base_url.rstrip("/") + "/youtube/transcript"
    headers: dict[str, str] = {}
    if config.gateway_api_key:
        headers["X-API-Key"] = config.gateway_api_key

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                endpoint,
                json={
                    "video_url": url,
                    "formatter": "text",
                    "backend": "auto",
                    "include_duration": True,
                },
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
        duration = data.get("duration_seconds")
        duration_int = int(duration) if isinstance(duration, (int, float)) and duration > 0 else None
        return transcript, duration_int
    if resp.status_code == 404:
        raise TldrError("no_transcript")
    logger.error("Gateway transcript returned %d: %s", resp.status_code, resp.text[:200])
    raise TldrError("transcript_error")



def _build_prompt(
    content: str,
    source_desc: str,
    lang: str,
    question: str | None,
    instruction_override: str | None = None,
) -> str:
    """Assemble the full prompt sent to the gateway LLM.

    instruction_override (when present) replaces the default TLDR_INSTRUCTION
    body. It is ignored when the user passed a focus question (that path uses
    the question template since the override doesn't know about the question).
    """
    if question:
        return _TLDR_QUESTION_BODY.format(
            source_desc=source_desc,
            question=question,
            lang=lang,
            format_rules=_FORMAT_RULES,
            content=content,
        )
    instruction = (instruction_override.strip()
                   if instruction_override and instruction_override.strip()
                   else TLDR_INSTRUCTION)
    if "{lang}" in instruction:
        instruction = instruction.format(lang=lang)
    body = _TLDR_BODY.format(
        source_desc=source_desc,
        format_rules=_FORMAT_RULES,
        content=content,
    )
    return instruction + "\n" + body


def parse_aliases(raw: str) -> list[str]:
    """Split comma-separated alias string, normalise each token."""
    return [a.strip().lower() for a in raw.split(",") if a.strip()]


def parse_domains(raw: str | None) -> list[str]:
    """Split comma-separated domain glob string, normalise each entry to lowercase."""
    if not raw:
        return []
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


@dataclass
class UserAliasEntry:
    """Resolved view of a single insight_tldr_aliases row.

    keys:     alias keywords this row binds (may be empty for pure domain rows)
    prompt:   custom prompt body (None when row binds to a built-in alias)
    domains:  glob patterns matched against 'host[/path]' lowercased
    target:   built-in alias name when row is a domain-binding shortcut
    """
    id: int
    keys: list[str]
    prompt: str | None
    domains: list[str]
    target: str | None

    @property
    def effective_alias(self) -> str | None:
        """Alias key to log/cache under: first keyword for custom rows, target for built-in binds."""
        if self.keys:
            return self.keys[0]
        return self.target


def _url_match_key(url: str) -> str:
    """Build the lowercase 'host/path' string we match globs against."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        return host + path
    except Exception:
        return url.lower()


def match_domain(url: str, entries: list[UserAliasEntry]) -> UserAliasEntry | None:
    """Return the first alias entry whose domain glob matches the URL.

    Match rules (fnmatch on lowercased 'host[/path]'):
      'example.com'     -> exact host (path ignored: matches when key == host)
      'example.com/*'   -> host + any path
      '*.lwn.net'       -> host glob (path ignored)
    """
    key = _url_match_key(url)
    host = key.split("/", 1)[0]
    for e in entries:
        for pat in e.domains:
            if "/" in pat:
                if fnmatch.fnmatchcase(key, pat):
                    return e
            else:
                if fnmatch.fnmatchcase(host, pat):
                    return e
    return None


def resolve_alias_prompt(
    alias_key: str | None,
    entries: list[UserAliasEntry] | None = None,
    lang: str = "en",
) -> str | None:
    """Resolve an alias keyword to its prompt body. Returns None on miss.

    Lookup order: built-in -> user entries (by any matched keyword).
    """
    if not alias_key:
        return None
    key = alias_key.strip().lower()
    if key in _BUILTIN_ALIASES:
        prompt = _BUILTIN_ALIASES[key]
        return prompt.format(lang=lang) if "{lang}" in prompt else prompt
    if entries:
        for e in entries:
            if key in e.keys:
                if e.prompt is not None:
                    return e.prompt
                if e.target and e.target in _BUILTIN_ALIASES:
                    bp = _BUILTIN_ALIASES[e.target]
                    return bp.format(lang=lang) if "{lang}" in bp else bp
    return None


def alias_header_key(alias_key: str | None) -> str:
    """Return the i18n key to use as Telegram message header for this alias."""
    if not alias_key:
        return "tldr.header"
    key = alias_key.strip().lower()
    return _BUILTIN_ALIAS_HEADER_KEY.get(key, "tldr.header")


@dataclass
class PreparedTldr:
    """Content + metrics ready to feed into the LLM.

    is_youtube tells the caller whether video_seconds was applicable;
    video_seconds is None when the gateway returned no duration AND the
    source is not YouTube.
    """
    content: str
    source_desc: str
    is_youtube: bool
    video_seconds: int | None
    via: str


async def prepare_tldr(
    url: str,
    config: InsightConfig,
    github_token: str | None = None,
    use_search: bool = False,
) -> PreparedTldr:
    """Fetch content for the URL and capture size + duration metrics.

    When use_search=True the gateway answer engine (/v1/search, mode=raw) is
    tried first; on any failure we fall back to the legacy trafilatura/jina
    stack so the user never gets stuck waiting.

    Raises TldrError on fetch failure.
    """
    is_yt = _is_youtube(url)
    if is_yt:
        content, duration = await _fetch_youtube_transcript(url, config)
        return PreparedTldr(
            content=content,
            source_desc=f"YouTube video ({url})",
            is_youtube=True,
            video_seconds=duration,
            via="gateway:youtube",
        )

    if use_search:
        try:
            search_result = await search_fetch(
                url, config,
                max_content_chars=config.tldr_max_content_chars,
            )
            joined = join_sources_for_llm(search_result.sources)
            if joined.strip():
                parsed = urlparse(url)
                return PreparedTldr(
                    content=joined[: config.tldr_max_content_chars],
                    source_desc=parsed.netloc + parsed.path,
                    is_youtube=False,
                    video_seconds=None,
                    via=search_result.via,
                )
            logger.info("gateway /v1/search returned empty content for %s, falling back", url)
        except SearchFetchError as exc:
            logger.info("gateway /v1/search failed (%s) for %s, falling back", exc.args, url)
        except Exception as exc:
            logger.warning("gateway /v1/search unexpected error for %s: %s", url, exc)

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
    parsed = urlparse(url)
    return PreparedTldr(
        content=result.content,
        source_desc=parsed.netloc + parsed.path,
        is_youtube=False,
        video_seconds=None,
        via=result.via,
    )


@dataclass
class ByokRoute:
    """Inputs for routing /tldr through a user-owned provider instead of the gateway.

    provider/base_url/api_key/model come straight from insight_user_byok.
    When present, stream_llm bypasses the gateway entirely.
    """
    provider: str
    base_url: str | None
    api_key: str
    model: str


async def stream_llm(
    prepared: PreparedTldr,
    lang: str,
    config: InsightConfig,
    alias_key: str | None = None,
    question: str | None = None,
    model: str | None = None,
    entries: list[UserAliasEntry] | None = None,
    default_instruction_override: str | None = None,
    byok: ByokRoute | None = None,
):
    """Stream LLM summary chunks for an already-prepared content blob.

    Yields str chunks. Raises TldrError on failure.

    alias_key takes precedence over question: when set, the resolved alias
    prompt is used; otherwise the free-text question (if any) drives the
    question-style prompt. default_instruction_override only kicks in when
    no alias and no question are present - the user's custom TLDR default.

    When byok is set the user-provided provider is called directly, bypassing
    the gateway. The 'model' kwarg is ignored in that branch (byok.model wins).
    """
    resolved_question: str | None = None
    if alias_key:
        resolved_question = resolve_alias_prompt(alias_key, entries, lang=lang)
    elif question:
        resolved_question = question
    prompt = _build_prompt(
        prepared.content, prepared.source_desc, lang, resolved_question,
        instruction_override=default_instruction_override if not alias_key and not question else None,
    )

    if byok is not None:
        try:
            base = resolve_base_url(byok.provider, byok.base_url)
        except BYOKError as exc:
            logger.error("BYOK base url resolution failed: %s", exc)
            raise TldrError("llm_error") from exc
        try:
            async for delta in byok_stream_chat(byok.provider, base, byok.api_key, byok.model, prompt):
                yield delta
        except BYOKError as exc:
            code = exc.args[0] if exc.args else "llm_error"
            raise TldrError(code) from exc
        return

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
