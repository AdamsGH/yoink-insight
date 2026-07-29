"""/tldr <url> [question] - fetch and summarise any URL via gateway LLM."""
from __future__ import annotations

import asyncio
import logging

from telegram import Message, MessageEntity, Update
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes

from yoink.core.bot.access import AccessPolicy, require_access
from yoink.core.db.models import UserRole
from yoink.core.i18n.loader import t
from sqlalchemy import select

from yoink_insight.bot.middleware import get_effective_insight_config, get_insight_settings_repo, get_insight_usage_repo
from yoink_insight.services.md_entities import _utf16_len, md_to_entities
from yoink_insight.services.tldr import (
    TldrError,
    UserAliasEntry,
    _BUILTIN_ALIASES,
    alias_header_key,
    cache_key_for_url,
    match_domain,
    parse_aliases,
    parse_domains,
    prepare_tldr,
    resolve_tldr_route,
    stream_llm,
)

# Telegram hard cap is 4096 UTF-16 code units per message. We keep a safety
# margin: the body must fit under TG_BODY_LIMIT_U16 after the header line
# (header + "\n\n") is prepended. The streamed draft uses TG_DRAFT_LIMIT_U16,
# which is tighter so a still-growing accumulated string has room for one
# more chunk before crossing 4096.
_TG_HARD_LIMIT_U16 = 4096
_TG_DRAFT_LIMIT_U16 = 3800

logger = logging.getLogger(__name__)

# Send a draft update each time the buffered output grows by at least this many
# characters since the last push.
_DRAFT_MIN_CHARS = 80

# Minimum seconds between two draft updates. Telegram throttles editMessage
# (and the draft wrapper around it) around ~1/s per chat; without this gate a
# fast-streaming model floods Bot API with Flood-control 429s on every chunk.
_DRAFT_MIN_INTERVAL = 1.5


def _draft_id_for(msg: Message) -> int:
    """Stable per-chat draft id. We reuse the user's message id, which is
    unique within the chat and stable for the lifetime of the request."""
    return msg.message_id


def _split_markdown_for_telegram(body: str, header_u16: int, hard_limit_u16: int = _TG_HARD_LIMIT_U16) -> list[str]:
    """Split a markdown body into chunks that each fit under hard_limit_u16
    UTF-16 code units AFTER the header line is prepended.

    Splits preferentially on blank lines (paragraph boundary), then single
    newlines, then sentence punctuation, then whitespace. Code fences are
    kept intact when possible: a chunk never starts or ends in the middle
    of a ```fenced block``` unless the fence itself is bigger than the
    available budget (in which case it is split as a last resort).

    The first chunk's budget is hard_limit_u16 - header_u16 (header sits on
    chunk #1 only); subsequent chunks use the full hard_limit_u16.
    """
    body = body.strip()
    if not body:
        return []

    chunks: list[str] = []
    remaining = body
    is_first = True

    while remaining:
        budget = hard_limit_u16 - (header_u16 if is_first else 0)
        if _utf16_len(remaining) <= budget:
            chunks.append(remaining.strip())
            break

        # Find the largest prefix that fits the budget. We approximate the
        # cut point in characters first (UTF-16 len >= char len), then
        # tighten by walking back to a logical boundary.
        cut = _find_cut_index(remaining, budget)
        head = remaining[:cut].rstrip()
        tail = remaining[cut:].lstrip()

        # If a code fence is open in `head` (odd number of ``` markers),
        # close it for the chunk and reopen it for the tail so each chunk
        # is independently parseable.
        if head.count("```") % 2 == 1:
            head = head + "\n```"
            tail = "```\n" + tail

        chunks.append(head)
        remaining = tail
        is_first = False

    return chunks


def _find_cut_index(s: str, budget_u16: int) -> int:
    """Return a character index where s can be split so the prefix fits
    budget_u16 UTF-16 code units, preferring paragraph > line > sentence >
    word > raw cut. Always returns a positive int (>= 1) so the loop in
    _split_markdown_for_telegram makes progress.
    """
    # Walk forward accumulating UTF-16 length until we'd exceed the budget;
    # max_idx is the largest valid raw cut.
    acc = 0
    max_idx = len(s)
    for i, c in enumerate(s):
        step = 2 if ord(c) > 0xFFFF else 1
        if acc + step > budget_u16:
            max_idx = i
            break
        acc += step
    if max_idx <= 0:
        return 1

    window = s[:max_idx]
    # Prefer a blank-line boundary in the second half of the window.
    half = max_idx // 2
    for sep in ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "):
        idx = window.rfind(sep)
        if idx >= half:
            return idx + len(sep)
    # Fall back to whatever we have past halfway, else the raw cut.
    for sep in ("\n\n", "\n", ". ", "? ", "! ", "; ", " "):
        idx = window.rfind(sep)
        if idx > 0:
            return idx + len(sep)
    return max_idx


async def _load_user_alias_entries(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[UserAliasEntry]:
    """Load this user's alias rows into the canonical UserAliasEntry view."""
    session_factory = context.bot_data.get("session_factory")
    if not session_factory:
        return []
    from yoink_insight.storage.models import InsightTldrAlias
    out: list[UserAliasEntry] = []
    async with session_factory() as session:
        rows = (await session.execute(
            select(InsightTldrAlias).where(InsightTldrAlias.user_id == user_id)
        )).scalars().all()
        for r in rows:
            out.append(UserAliasEntry(
                id=r.id,
                keys=parse_aliases(r.aliases) if r.aliases else [],
                prompt=r.prompt,
                domains=parse_domains(r.domains),
                target=r.target_alias,
            ))
    return out


@require_access(AccessPolicy(
    min_role=UserRole.user,
    plugin="insight",
    feature="tldr",
    scopes=["all"],
    silent_deny=False,
    group_silent_deny=True,
))
async def _cmd_tldr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    settings = get_insight_settings_repo(context)
    config = await get_effective_insight_config(context)
    lang = await settings.get_lang(user_id, default=config.insight_default_lang)

    args = context.args or []
    if not args:
        await update.message.reply_html(t("tldr.no_url", lang))
        return

    url = args[0]
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    question = " ".join(args[1:]).strip() or None

    usage_repo = get_insight_usage_repo(context)
    if config.tldr_rate_limit_per_day > 0:
        used_today = await usage_repo.count_today_command(user_id, "tldr")
        if used_today >= config.tldr_rate_limit_per_day:
            await update.message.reply_html(
                t("tldr.error.rate_limited", lang,
                  limit=config.tldr_rate_limit_per_day,
                  fallback=t("insight.error.generic", lang)),
            )
            return

    user_model = await settings.get_tldr_model(user_id)
    user_github_token = await settings.get_github_token(user_id)
    byok_route = await resolve_tldr_route(user_id, context)
    route = "byok" if byok_route is not None else "gateway"

    entries = await _load_user_alias_entries(context, user_id)

    # Resolve alias_key: explicit question matching a known keyword, or
    # a domain binding when the user passed no question.
    alias_key: str | None = None
    user_keys: set[str] = set()
    for e in entries:
        user_keys.update(e.keys)
    if question is not None:
        candidate = question.strip().lower()
        if candidate in _BUILTIN_ALIASES or candidate in user_keys:
            alias_key = candidate
    elif question is None:
        match = match_domain(url, entries)
        if match is not None:
            alias_key = match.effective_alias

    # Cache: alias-keyed entries share their bucket so domain-binding and
    # explicit "/tldr <url> noshit" hit the same row.
    cache_repo = context.bot_data.get("insight_summary_cache")
    ck = cache_key_for_url(url)
    cache_cmd = f"tldr:{alias_key}" if alias_key else "tldr"
    cache_eligible = (question is None) or (alias_key is not None)
    if cache_eligible:
        cache_cmd += ":v2"
    cached = await cache_repo.get(ck, lang, cache_cmd) if (cache_repo and cache_eligible) else None
    header = t(alias_header_key(alias_key), lang)
    header_len_u16 = _utf16_len(header)

    # Header gets two overlapping entities on the same span: bold + text_link
    # to the source URL, so the title visibly stays "Summary" while clicking
    # opens the original.
    def _header_entities() -> list[MessageEntity]:
        return [
            MessageEntity(type=MessageEntity.BOLD, offset=0, length=header_len_u16),
            MessageEntity(type=MessageEntity.TEXT_LINK, offset=0, length=header_len_u16, url=url),
        ]

    bot = context.bot
    chat_id = update.message.chat_id
    thread_id = getattr(update.message, "message_thread_id", None)
    draft_id = _draft_id_for(update.message)
    reply_to = update.message.message_id

    async def _send_body_chunks(body_md: str) -> None:
        """Render body_md to entities and send it as one or more messages.

        The header (bold + text_link) is attached to chunk #1 only. Each
        chunk is parsed independently via md_to_entities, so entity
        offsets stay valid even when the body has to be split across
        Telegram's 4096 UTF-16 limit. Falls back to plain text if the
        entities trip a BadRequest.
        """
        header_line = f"{header}\n\n"
        header_u16 = _utf16_len(header_line)
        md_chunks = _split_markdown_for_telegram(body_md, header_u16)
        for i, md_chunk in enumerate(md_chunks):
            plain_part, part_entities = md_to_entities(md_chunk)
            if i == 0:
                text = header_line + plain_part
                offset_shift = header_u16
                ents = _header_entities() + [
                    MessageEntity(type=e["type"], offset=e["offset"] + offset_shift,
                                  length=e["length"], url=e.get("url"))
                    for e in part_entities
                ]
                reply_arg: int | None = reply_to
            else:
                text = plain_part
                ents = [
                    MessageEntity(type=e["type"], offset=e["offset"],
                                  length=e["length"], url=e.get("url"))
                    for e in part_entities
                ]
                reply_arg = None
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    entities=ents,
                    reply_to_message_id=reply_arg,
                    message_thread_id=thread_id,
                )
            except BadRequest as exc:
                logger.warning("send_message with entities failed (%s), falling back to plain", exc)
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_to_message_id=reply_arg,
                    message_thread_id=thread_id,
                )

    if cached:
        await _send_body_chunks(cached)
        await usage_repo.log(user_id, "tldr", lang=lang, status="cached", alias_key=alias_key, route=route)
        return

    # Bot API 10.0 docs claim sendMessageDraft accepts text="" to render a
    # "Thinking..." placeholder, but the live server still rejects it with
    # "Text must be non-empty". Until that lands, we just skip the initial
    # placeholder and start the draft on the first real chunk below; the
    # standard chat-action typing indicator (set elsewhere in the runner)
    # carries the "working" cue in the meantime.
    draft_active = False
    draft_disabled = False

    async def _report_error(code: str, *, prepared_chars: int | None = None, prepared_seconds: int | None = None) -> None:
        err_text = t(f"tldr.error.{code}", lang, fallback=t("insight.error.generic", lang))
        try:
            await update.message.reply_html(err_text)
        except Exception as exc:
            logger.debug("Failed to deliver error reply: %s", exc)
        await usage_repo.log(
            user_id, "tldr", lang=lang, status="error", error_code=code,
            alias_key=alias_key,
            content_chars=prepared_chars,
            video_seconds=prepared_seconds,
            route=route,
        )

    # Fetch content + metrics first so they're available even if streaming fails.
    try:
        prepared = await prepare_tldr(url, config, github_token=user_github_token)
    except TldrError as exc:
        code = exc.args[0] if exc.args else "generic"
        await _report_error(code)
        return

    # One-line pipeline trace per /tldr invocation. Captures the inputs that
    # determine the LLM output (provider/model/transcript size) so a 'why did
    # the bot start talking about sore throats' bug can be diagnosed from logs
    # alone. Logged at INFO so it survives default-level filtering.
    if byok_route is not None:
        llm_desc = f"byok={byok_route.provider}:{byok_route.model}"
    else:
        llm_desc = f"gateway:{user_model or config.tldr_llm_model}"
    logger.info(
        "tldr user=%s url=%s via=%s %s content_chars=%d video_seconds=%s alias=%s question=%s",
        user_id, url, prepared.via, llm_desc, len(prepared.content),
        prepared.video_seconds, alias_key, bool(question),
    )

    accumulated = ""
    last_sent_len = 0

    last_sent_at = 0.0
    try:
        async for chunk in stream_llm(
            prepared, lang, config,
            alias_key=alias_key,
            question=question if alias_key is None else None,
            model=user_model,
            entries=entries,
            byok=byok_route,
        ):
            accumulated += chunk
            now = asyncio.get_event_loop().time()
            if draft_disabled:
                continue
            if (
                len(accumulated) - last_sent_len >= _DRAFT_MIN_CHARS
                and now - last_sent_at >= _DRAFT_MIN_INTERVAL
            ):
                try:
                    draft_plain, draft_entities = md_to_entities(accumulated.strip())
                    draft_header_line = f"{header}\n\n"
                    draft_offset = _utf16_len(draft_header_line)
                    draft_full_text = draft_header_line + draft_plain
                    # Once the streamed accumulator outgrows what one
                    # Telegram message can hold, drafts stop being useful:
                    # editMessage rejects them with Message_too_long and
                    # every subsequent chunk re-fails. Turn drafts off
                    # for the rest of the stream; the final send below
                    # splits the body into multiple messages anyway.
                    if _utf16_len(draft_full_text) > _TG_DRAFT_LIMIT_U16:
                        draft_disabled = True
                        continue
                    draft_full_entities = _header_entities() + [
                        MessageEntity(type=e["type"], offset=e["offset"] + draft_offset,
                                      length=e["length"], url=e.get("url"))
                        for e in draft_entities
                    ]
                    await bot.send_message_draft(
                        chat_id=chat_id,
                        draft_id=draft_id,
                        text=draft_full_text,
                        entities=draft_full_entities,
                        message_thread_id=thread_id,
                    )
                    draft_active = True
                    last_sent_len = len(accumulated)
                    last_sent_at = now
                except Exception as draft_err:
                    logger.debug("sendMessageDraft failed (non-fatal): %s", draft_err)

    except TldrError as exc:
        code = exc.args[0] if exc.args else "generic"
        await _report_error(code, prepared_chars=len(prepared.content), prepared_seconds=prepared.video_seconds)
        return

    body = accumulated.strip()
    if not body:
        await _report_error("empty_response", prepared_chars=len(prepared.content), prepared_seconds=prepared.video_seconds)
        return

    # The active draft is ephemeral and auto-expires when sendMessage lands
    # for the same chat; we don't have to delete it explicitly (and there's
    # no API for that anyway). Per Telegram docs: "the streamed draft is
    # ephemeral and acts as a temporary 30-second preview - once the output
    # is finalized, you must call sendMessage with the complete message to
    # persist it in the user's chat".
    #
    # _send_body_chunks splits the markdown body on paragraph / sentence
    # boundaries when it would otherwise overflow Telegram's 4096 UTF-16
    # cap, then renders each chunk to entities independently. Header is
    # attached to chunk #1 only.
    await _send_body_chunks(body)

    if cache_repo and cache_eligible:
        try:
            await cache_repo.set(ck, lang, cache_cmd, body)
        except Exception as cache_err:
            logger.debug("Failed to cache tldr result: %s", cache_err)

    await usage_repo.log(
        user_id, "tldr", lang=lang, status="ok",
        alias_key=alias_key,
        content_chars=len(prepared.content),
        video_seconds=prepared.video_seconds,
        route=route,
    )

    del draft_active  # presence is for future cleanup hooks


def register(app: Application) -> None:
    app.add_handler(CommandHandler("tldr", _cmd_tldr))
