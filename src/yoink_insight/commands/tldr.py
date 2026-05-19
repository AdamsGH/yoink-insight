"""/tldr <url> [question] - fetch and summarise any URL via gateway LLM."""
from __future__ import annotations

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
from yoink_insight.services.tldr import TldrError, _BUILTIN_ALIASES, alias_header_key, cache_key_for_url, stream_tldr

logger = logging.getLogger(__name__)

_DRAFT_MIN_CHARS = 80


def _draft_id(msg: Message) -> int:
    return msg.message_id


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

    thinking_msg = await update.message.reply_html(t("insight.thinking", lang))

    user_model = await settings.get_tldr_model(user_id)
    user_github_token = await settings.get_github_token(user_id)

    # Load user aliases from DB
    user_aliases: dict[str, str] = {}
    session_factory = context.bot_data.get("session_factory")
    if session_factory:
        from yoink_insight.storage.models import InsightTldrAlias
        async with session_factory() as session:
            rows = (await session.execute(
                select(InsightTldrAlias).where(InsightTldrAlias.user_id == user_id)
            )).scalars().all()
            user_aliases = {r.alias: r.prompt for r in rows}

    # Determine if question is an alias (aliases don't bypass cache - they modify the default prompt)
    is_alias = question is not None and question.strip().lower() in {**_BUILTIN_ALIASES, **user_aliases}
    cache_repo = context.bot_data.get("insight_summary_cache")
    ck = cache_key_for_url(url)
    cache_cmd = f"tldr:{question.strip().lower()}" if is_alias else "tldr"
    cached = await cache_repo.get(ck, lang, cache_cmd) if (cache_repo and (not question or is_alias)) else None
    header = t(alias_header_key(question, user_aliases), lang)
    if cached:
        plain_body, body_entities = md_to_entities(cached)
        header_line = f"{header}\n\n"
        offset_shift = _utf16_len(header_line)
        final_entities = [
            MessageEntity(type=MessageEntity.BOLD, offset=0, length=_utf16_len(header)),
        ] + [
            MessageEntity(type=e["type"], offset=e["offset"] + offset_shift,
                          length=e["length"], url=e.get("url"))
            for e in body_entities
        ]
        try:
            await thinking_msg.edit_text(
                header_line + plain_body,
                entities=final_entities,
            )
        except BadRequest:
            await thinking_msg.edit_text(header_line + plain_body)
        await usage_repo.log(user_id, "tldr", lang=lang, status="cached")
        return

    bot = thinking_msg.get_bot()
    chat_id = thinking_msg.chat_id
    thread_id = getattr(thinking_msg, "message_thread_id", None)
    draft_id = _draft_id(thinking_msg)
    reply_to = thinking_msg.reply_to_message.message_id if thinking_msg.reply_to_message else None

    accumulated = ""
    last_sent_len = 0

    try:
        async for chunk in stream_tldr(url, lang, config, question=question, model=user_model, github_token=user_github_token, user_aliases=user_aliases):
            accumulated += chunk
            if len(accumulated) - last_sent_len >= _DRAFT_MIN_CHARS:
                try:
                    draft_plain, draft_entities = md_to_entities(accumulated.strip())
                    draft_header_line = f"{header}\n\n"
                    draft_offset = _utf16_len(draft_header_line)
                    draft_full_text = draft_header_line + draft_plain
                    draft_full_entities = [
                        MessageEntity(type=MessageEntity.BOLD, offset=0, length=_utf16_len(header)),
                    ] + [
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
        err_text = t(f"tldr.error.{code}", lang, fallback=t("insight.error.generic", lang))
        await thinking_msg.edit_text(err_text, parse_mode="HTML")
        await usage_repo.log(user_id, "tldr", lang=lang, status="error", error_code=code)
        return

    body = accumulated.strip()
    if not body:
        await thinking_msg.edit_text(
            t("insight.error.empty_response", lang, fallback=t("insight.error.generic", lang)),
            parse_mode="HTML",
        )
        await usage_repo.log(user_id, "tldr", lang=lang, status="error", error_code="empty_response")
        return

    # Convert markdown body to plain text + MessageEntity list.
    # Header is prepended as a bold entity on top.
    plain_body, body_entities = md_to_entities(body)
    header_line = f"{header}\n\n"
    offset_shift = _utf16_len(header_line)
    final_text = header_line + plain_body
    final_entities = [
        MessageEntity(type=MessageEntity.BOLD, offset=0, length=_utf16_len(header)),
    ] + [
        MessageEntity(
            type=e["type"],
            offset=e["offset"] + offset_shift,
            length=e["length"],
            url=e.get("url"),
        )
        for e in body_entities
    ]
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

    try:
        await thinking_msg.delete()
    except Exception:
        pass

    cache_cmd = f"tldr:{question.strip().lower()}" if is_alias else "tldr"
    if cache_repo and (not question or is_alias):
        try:
            await cache_repo.set(ck, lang, cache_cmd, body)
        except Exception as cache_err:
            logger.debug("Failed to cache tldr result: %s", cache_err)

    await usage_repo.log(user_id, "tldr", lang=lang, status="ok")


def register(app: Application) -> None:
    app.add_handler(CommandHandler("tldr", _cmd_tldr))
