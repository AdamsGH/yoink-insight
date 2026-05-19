"""/tldr <url> [question] - fetch and summarise any URL via gateway LLM."""
from __future__ import annotations

import logging

from telegram import Message, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from yoink.core.bot.access import AccessPolicy, require_access
from yoink.core.db.models import UserRole
from yoink.core.i18n.loader import t
from yoink_insight.bot.middleware import get_effective_insight_config, get_insight_settings_repo, get_insight_usage_repo
from yoink_insight.services.tldr import TldrError, cache_key_for_url, stream_tldr

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

    # Rate-limit check (reuses the tldr-specific counter via command="tldr")
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

    # Per-user model override
    user_model = await settings.get_tldr_model(user_id)

    # Cache lookup
    cache_repo = context.bot_data.get("insight_summary_cache")
    ck = cache_key_for_url(url)
    cached = await cache_repo.get(ck, lang, "tldr") if cache_repo else None
    if cached:
        header = t("tldr.header", lang)
        await thinking_msg.edit_text(f"{header}\n\n{cached}", parse_mode="HTML")
        await usage_repo.log(user_id, "tldr", lang=lang, status="cached")
        return

    header = t("tldr.header", lang)
    bot = thinking_msg.get_bot()
    chat_id = thinking_msg.chat_id
    thread_id = getattr(thinking_msg, "message_thread_id", None)
    draft_id = _draft_id(thinking_msg)

    accumulated = ""
    last_sent_len = 0

    try:
        async for chunk in stream_tldr(url, lang, config, question=question, model=user_model):
            accumulated += chunk
            if len(accumulated) - last_sent_len >= _DRAFT_MIN_CHARS:
                try:
                    await bot.send_message_draft(
                        chat_id=chat_id,
                        draft_id=draft_id,
                        text=f"{header}\n\n{accumulated}",
                        parse_mode="HTML",
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

    if not accumulated.strip():
        await thinking_msg.edit_text(
            t("insight.error.empty_response", lang, fallback=t("insight.error.generic", lang)),
            parse_mode="HTML",
        )
        await usage_repo.log(user_id, "tldr", lang=lang, status="error", error_code="empty_response")
        return

    final_text = f"{header}\n\n{accumulated.strip()}"
    await bot.send_message(
        chat_id=chat_id,
        text=final_text,
        parse_mode="HTML",
        reply_to_message_id=thinking_msg.reply_to_message.message_id if thinking_msg.reply_to_message else None,
        message_thread_id=thread_id,
    )
    try:
        await thinking_msg.delete()
    except Exception:
        pass

    if cache_repo:
        try:
            await cache_repo.set(ck, lang, "tldr", accumulated.strip())
        except Exception as cache_err:
            logger.debug("Failed to cache tldr result: %s", cache_err)

    await usage_repo.log(user_id, "tldr", lang=lang, status="ok")


def register(app: Application) -> None:
    app.add_handler(CommandHandler("tldr", _cmd_tldr))
