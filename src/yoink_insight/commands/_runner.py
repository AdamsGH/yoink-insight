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
) -> None:
    """Stream a Gemini response into thinking_msg via sendMessageDraft, then finalize.

    Flow:
      1. Check cache - if hit, edit thinking_msg directly and return.
      2. Start Gemini streaming - send progressive drafts via sendMessageDraft.
      3. On completion - finalize with edit_text (persists in chat).
      4. Cache the result.
    """
    video_id = _extract_video_id(url)

    # Cache hit - instant response
    cached = await cache_repo.get(video_id, lang, command) if video_id else None
    if cached:
        await thinking_msg.edit_text(f"{header}\n\n{cached}", parse_mode="HTML")
        await usage_repo.log(user_id, command, video_id=video_id, lang=lang, status="cached")
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

    # Finalize - replaces the "thinking" message with the real content
    final_text = f"{header}\n\n{accumulated.strip()}"
    await thinking_msg.edit_text(final_text, parse_mode="HTML")

    # Cache for future requests
    if video_id:
        try:
            await cache_repo.set(video_id, lang, command, accumulated.strip())
        except Exception as cache_err:
            logger.debug("Failed to cache insight result: %s", cache_err)

    await usage_repo.log(user_id, command, video_id=video_id, lang=lang, status="ok")
