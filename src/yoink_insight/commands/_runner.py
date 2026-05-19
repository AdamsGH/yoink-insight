"""Shared runner for /summary and /about - streaming via sendMessageDraft."""
from __future__ import annotations

import logging

from telegram import Message

from yoink.core.i18n.loader import t
from yoink_insight.services.gemini import GeminiSummarizer, InsightError, _extract_video_id
from yoink_insight.storage.repos import InsightSummaryCacheRepo, InsightUsageLogRepo

logger = logging.getLogger(__name__)

# Minimum characters accumulated before sending a draft update.
# Avoids flooding the API with tiny incremental edits.
_DRAFT_MIN_CHARS = 80

# draft_id is per-message; we use message_id as a stable unique int.
def _draft_id(msg: Message) -> int:
    return msg.message_id


async def run_insight_command(
    *,
    command: str,
    url: str,
    lang: str,
    thinking_msg: Message,
    header: str,
    summarizer: GeminiSummarizer,
    cache_repo: InsightSummaryCacheRepo,
    usage_repo: InsightUsageLogRepo,
    user_id: int,
    rate_limit_per_day: int = 0,
) -> None:
    """Stream a Gemini response into thinking_msg via sendMessageDraft, then finalize.

    Flow:
      1. Check cache - if hit, edit thinking_msg directly and return.
      2. Start Gemini streaming - send progressive drafts via sendMessageDraft.
      3. On completion - finalize with edit_text (persists in chat).
      4. Cache the result.
    """
    video_id = _extract_video_id(url)
    # For /summary and /about the cache key is the bare video ID.
    cache_key = video_id

    # Cache hit - instant response (does not count against rate limit)
    cached = await cache_repo.get(cache_key, lang, command) if cache_key else None
    if cached:
        await thinking_msg.edit_text(f"{header}\n\n{cached}", parse_mode="HTML")
        await usage_repo.log(user_id, command, video_id=video_id, lang=lang, status="cached")
        return

    # Rate-limit gate (only fresh API calls count; 0 disables)
    if rate_limit_per_day > 0:
        used_today = await usage_repo.count_today(user_id)
        if used_today >= rate_limit_per_day:
            await thinking_msg.edit_text(
                t("insight.error.rate_limited", lang, limit=rate_limit_per_day,
                  fallback=t("insight.error.generic", lang)),
                parse_mode="HTML",
            )
            await usage_repo.log(
                user_id, command, video_id=video_id, lang=lang,
                status="error", error_code="rate_limited",
            )
            return

    bot = thinking_msg.get_bot()
    chat_id = thinking_msg.chat_id
    thread_id = getattr(thinking_msg, "message_thread_id", None)
    draft_id = _draft_id(thinking_msg)

    accumulated = ""
    last_sent_len = 0

    try:
        async for chunk in summarizer.stream_command(url, lang, command):
            accumulated += chunk
            # Send draft update when we have enough new content
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
                    # sendMessageDraft may not be supported on older clients - non-fatal
                    logger.debug("sendMessageDraft failed (non-fatal): %s", draft_err)

    except InsightError as exc:
        key = f"insight.error.{exc.args[0]}" if exc.args else "insight.error.generic"
        err_text = t(key, lang, fallback=t("insight.error.generic", lang))
        await thinking_msg.edit_text(err_text, parse_mode="HTML")
        await usage_repo.log(
            user_id, command, video_id=video_id, lang=lang,
            status="error", error_code=exc.args[0] if exc.args else "generic",
        )
        return

    if not accumulated.strip():
        await thinking_msg.edit_text(
            t("insight.error.empty_response", lang, fallback=t("insight.error.generic", lang)),
            parse_mode="HTML",
        )
        await usage_repo.log(user_id, command, video_id=video_id, lang=lang, status="error", error_code="empty_response")
        return

    # Finalize: send permanent message, then delete the "thinking" placeholder.
    # edit_text on thinking_msg leaves the draft dangling ("typing" indicator stays).
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

    # Cache for future requests
    if cache_key:
        try:
            await cache_repo.set(cache_key, lang, command, accumulated.strip())
        except Exception as cache_err:
            logger.debug("Failed to cache insight result: %s", cache_err)

    await usage_repo.log(user_id, command, video_id=video_id, lang=lang, status="ok")
