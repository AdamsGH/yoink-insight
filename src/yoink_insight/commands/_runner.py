"""Shared runner for /summary and /about - delayed-thinking + streaming.

Same UX pattern as /tldr: no "Thinking..." placeholder is posted up-front;
instead an asyncio timer schedules it for _THINKING_DELAY seconds in the
future, and it is only created if the LLM keeps quiet that long. The
placeholder is removed before the final reply lands so the chat scrolls
once, not twice.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import Message, Update
from telegram.ext import ContextTypes

from yoink.core.i18n.loader import t
from yoink_insight.services.gemini import GeminiSummarizer, InsightError, _extract_video_id
from yoink_insight.storage.repos import InsightSummaryCacheRepo, InsightUsageLogRepo

logger = logging.getLogger(__name__)

# Show "Thinking..." only after this many seconds without any visible progress.
# If Gemini starts streaming before that, the placeholder never appears.
_THINKING_DELAY = 8.0

# Minimum characters accumulated before sending a draft update.
_DRAFT_MIN_CHARS = 80

# Minimum seconds between two draft updates. Telegram throttles editMessage
# (and the draft wrapper around it) hard around ~1/s per chat; bursting past
# that triggers Flood control on every subsequent edit until the stream ends.
_DRAFT_MIN_INTERVAL = 1.5


def _draft_id(message_id: int) -> int:
    """Stable per-chat draft id: the user's command-message id."""
    return message_id


async def run_insight_command(
    *,
    command: str,
    url: str,
    lang: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    header: str,
    summarizer: GeminiSummarizer,
    cache_repo: InsightSummaryCacheRepo,
    usage_repo: InsightUsageLogRepo,
    user_id: int,
    rate_limit_per_day: int = 0,
    prompt_override: str | None = None,
) -> None:
    """Run the gemini-backed /summary or /about command end to end.

    Cache check, rate-limit gate, streaming, and final delivery all happen
    here. The caller is responsible only for validating the URL and
    constructing the GeminiSummarizer.
    """
    if not update.message:
        return

    video_id = _extract_video_id(url)
    cache_key = video_id

    # Cache hit -> instant reply, no placeholder, no draft.
    cached = await cache_repo.get(cache_key, lang, command) if cache_key else None
    if cached:
        await update.message.reply_text(f"{header}\n\n{cached}", parse_mode="HTML")
        await usage_repo.log(user_id, command, video_id=video_id, lang=lang, status="cached")
        return

    if rate_limit_per_day > 0:
        used_today = await usage_repo.count_today(user_id)
        if used_today >= rate_limit_per_day:
            await update.message.reply_html(
                t("insight.error.rate_limited", lang, limit=rate_limit_per_day,
                  fallback=t("insight.error.generic", lang)),
            )
            await usage_repo.log(
                user_id, command, video_id=video_id, lang=lang,
                status="error", error_code="rate_limited",
            )
            return

    bot = context.bot
    chat_id = update.message.chat_id
    thread_id = getattr(update.message, "message_thread_id", None)
    draft_id = _draft_id(update.message.message_id)
    reply_to = update.message.message_id

    # Lazy "Thinking..." placeholder, posted only if Gemini keeps quiet past
    # _THINKING_DELAY. Tracked by ref so finally/error paths can clean it up.
    thinking_msg: Message | None = None

    async def _post_thinking() -> None:
        nonlocal thinking_msg
        await asyncio.sleep(_THINKING_DELAY)
        try:
            thinking_msg = await update.message.reply_html(t("insight.thinking", lang))
        except Exception as exc:
            logger.debug("Posting thinking placeholder failed: %s", exc)

    thinking_task = asyncio.create_task(_post_thinking())

    async def _cleanup_thinking() -> None:
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

    accumulated = ""
    last_sent_len = 0
    last_sent_at = 0.0

    try:
        async for chunk in summarizer.stream_command(url, lang, command, prompt_override=prompt_override):
            accumulated += chunk
            now = asyncio.get_event_loop().time()
            if (
                len(accumulated) - last_sent_len >= _DRAFT_MIN_CHARS
                and now - last_sent_at >= _DRAFT_MIN_INTERVAL
            ):
                try:
                    await bot.send_message_draft(
                        chat_id=chat_id,
                        draft_id=draft_id,
                        text=f"{header}\n\n{accumulated}",
                        parse_mode="HTML",
                        message_thread_id=thread_id,
                    )
                    last_sent_len = len(accumulated)
                    last_sent_at = now
                except Exception as draft_err:
                    logger.debug("sendMessageDraft failed (non-fatal): %s", draft_err)

    except InsightError as exc:
        await _cleanup_thinking()
        key = f"insight.error.{exc.args[0]}" if exc.args else "insight.error.generic"
        err_text = t(key, lang, fallback=t("insight.error.generic", lang))
        try:
            await update.message.reply_html(err_text)
        except Exception as exc2:
            logger.debug("Failed to deliver error reply: %s", exc2)
        await usage_repo.log(
            user_id, command, video_id=video_id, lang=lang,
            status="error", error_code=exc.args[0] if exc.args else "generic",
        )
        return

    if not accumulated.strip():
        await _cleanup_thinking()
        try:
            await update.message.reply_html(
                t("insight.error.empty_response", lang, fallback=t("insight.error.generic", lang)),
            )
        except Exception as exc:
            logger.debug("Failed to deliver empty-response reply: %s", exc)
        await usage_repo.log(user_id, command, video_id=video_id, lang=lang, status="error", error_code="empty_response")
        return

    # Drop placeholder BEFORE sending the final message so the chat scrolls
    # exactly once (placeholder removal + final delivery merged).
    await _cleanup_thinking()

    final_text = f"{header}\n\n{accumulated.strip()}"
    await bot.send_message(
        chat_id=chat_id,
        text=final_text,
        parse_mode="HTML",
        reply_to_message_id=reply_to,
        message_thread_id=thread_id,
    )

    if cache_key:
        try:
            await cache_repo.set(cache_key, lang, command, accumulated.strip())
        except Exception as cache_err:
            logger.debug("Failed to cache insight result: %s", cache_err)

    await usage_repo.log(user_id, command, video_id=video_id, lang=lang, status="ok")
