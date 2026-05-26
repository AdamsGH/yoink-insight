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

from yoink_insight.bot.middleware import (
    get_effective_insight_config,
    get_insight_byok_repo,
    get_insight_prompts_repo,
    get_insight_settings_repo,
    get_insight_usage_repo,
    is_byok_enabled,
)
from yoink_insight.services.md_entities import _utf16_len, md_to_entities
from yoink_insight.services.tldr import (
    ByokRoute,
    TldrError,
    UserAliasEntry,
    _BUILTIN_ALIASES,
    alias_header_key,
    cache_key_for_url,
    match_domain,
    parse_aliases,
    parse_domains,
    prepare_tldr,
    stream_llm,
)

logger = logging.getLogger(__name__)

# Show "Thinking..." only after this many seconds without any visible progress.
# If the LLM starts streaming before that, the placeholder never appears.
_THINKING_DELAY = 8.0

# Send a draft update each time the buffered output grows by at least this many
# characters since the last push.
_DRAFT_MIN_CHARS = 80


def _draft_id_for(msg: Message) -> int:
    """Stable per-chat draft id. We reuse the user's message id, which is unique
    within the chat and stable for the lifetime of the request."""
    return msg.message_id


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


async def _resolve_tldr_access(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> tuple[bool, ByokRoute | None]:
    """Decide whether the user may run /tldr and which path to take.

    Returns (allowed, byok_route). byok_route is non-None when the user has
    no insight:tldr grant but the admin enabled BYOK and the user has saved a
    valid (probed-OK) config. Owners can always use the gateway path.
    """
    perm_repo = context.bot_data.get("perm_repo")
    user_repo = context.bot_data.get("user_repo")
    user = await user_repo.get_or_create(user_id) if user_repo is not None else None
    has_feature = False
    if perm_repo is not None:
        has_feature = await perm_repo.has(user_id, "insight", "tldr", user=user)
    if has_feature:
        return True, None

    if not await is_byok_enabled(context):
        return False, None

    byok_repo = get_insight_byok_repo(context)
    row = await byok_repo.get(user_id)
    if row is None or not row.api_key or not row.model or row.tested_at is None:
        return False, None
    return True, ByokRoute(
        provider=row.provider,
        base_url=row.base_url,
        api_key=row.api_key,
        model=row.model,
    )


@require_access(AccessPolicy(
    min_role=UserRole.user,
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

    allowed, byok_route = await _resolve_tldr_access(context, user_id)
    if not allowed:
        await update.message.reply_html(t("tldr.no_access", lang))
        return

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
    use_search = await settings.get_use_search(user_id)
    prompts_repo = get_insight_prompts_repo(context)
    user_tldr_prompt = await prompts_repo.get(user_id, "tldr")

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

    if cached:
        plain_body, body_entities = md_to_entities(cached)
        header_line = f"{header}\n\n"
        offset_shift = _utf16_len(header_line)
        final_entities = _header_entities() + [
            MessageEntity(type=e["type"], offset=e["offset"] + offset_shift,
                          length=e["length"], url=e.get("url"))
            for e in body_entities
        ]
        try:
            await update.message.reply_text(
                header_line + plain_body,
                entities=final_entities,
            )
        except BadRequest:
            await update.message.reply_text(header_line + plain_body)
        await usage_repo.log(user_id, "tldr", lang=lang, status="cached", alias_key=alias_key)
        return

    bot = context.bot
    chat_id = update.message.chat_id
    thread_id = getattr(update.message, "message_thread_id", None)
    draft_id = _draft_id_for(update.message)
    reply_to = update.message.message_id

    # Optional "Thinking..." placeholder, posted only if the LLM keeps quiet
    # past _THINKING_DELAY. We track it via a single mutable reference so
    # nested coroutines and finally-blocks can see the latest state.
    thinking_msg: Message | None = None
    thinking_failed = False

    async def _post_thinking() -> None:
        nonlocal thinking_msg, thinking_failed
        await asyncio.sleep(_THINKING_DELAY)
        try:
            thinking_msg = await update.message.reply_html(t("insight.thinking", lang))
        except Exception as exc:
            thinking_failed = True
            logger.debug("Posting thinking placeholder failed: %s", exc)

    thinking_task = asyncio.create_task(_post_thinking())

    async def _cleanup_thinking() -> None:
        """Cancel the pending placeholder or remove the live one. Safe to call
        multiple times."""
        if not thinking_task.done():
            thinking_task.cancel()
            try:
                await thinking_task
            except (asyncio.CancelledError, Exception):
                pass
        if thinking_msg is not None:
            try:
                await thinking_msg.delete()
            except Exception:
                pass

    async def _report_error(code: str, *, prepared_chars: int | None = None, prepared_seconds: int | None = None) -> None:
        await _cleanup_thinking()
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
        )

    # Fetch content + metrics first so they're available even if streaming fails.
    try:
        prepared = await prepare_tldr(
            url, config,
            github_token=user_github_token,
            use_search=use_search,
        )
    except TldrError as exc:
        code = exc.args[0] if exc.args else "generic"
        await _report_error(code)
        return

    accumulated = ""
    last_sent_len = 0

    try:
        async for chunk in stream_llm(
            prepared, lang, config,
            alias_key=alias_key,
            question=question if alias_key is None else None,
            model=user_model,
            entries=entries,
            default_instruction_override=user_tldr_prompt,
            byok=byok_route,
        ):
            accumulated += chunk
            if len(accumulated) - last_sent_len >= _DRAFT_MIN_CHARS:
                try:
                    draft_plain, draft_entities = md_to_entities(accumulated.strip())
                    draft_header_line = f"{header}\n\n"
                    draft_offset = _utf16_len(draft_header_line)
                    draft_full_text = draft_header_line + draft_plain
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
                    last_sent_len = len(accumulated)
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

    # Convert markdown body to plain text + MessageEntity list.
    plain_body, body_entities = md_to_entities(body)
    header_line = f"{header}\n\n"
    offset_shift = _utf16_len(header_line)
    final_text = header_line + plain_body
    final_entities = _header_entities() + [
        MessageEntity(
            type=e["type"],
            offset=e["offset"] + offset_shift,
            length=e["length"],
            url=e.get("url"),
        )
        for e in body_entities
    ]

    # Now that we're about to deliver the real reply, remove the placeholder
    # FIRST. This avoids the chat shifting twice (once when the placeholder
    # was added, once when the final message lands and the placeholder is
    # deleted afterwards).
    await _cleanup_thinking()

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=final_text,
            entities=final_entities,
            reply_to_message_id=reply_to,
            message_thread_id=thread_id,
        )
    except BadRequest as exc:
        logger.warning("send_message with entities failed (%s), falling back to plain", exc)
        await bot.send_message(
            chat_id=chat_id,
            text=final_text,
            reply_to_message_id=reply_to,
            message_thread_id=thread_id,
        )

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
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler("tldr", _cmd_tldr))
