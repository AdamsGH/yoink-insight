"""/about <url> - describe a YouTube video in 2-3 sentences."""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from yoink.core.bot.access import AccessPolicy, require_access
from yoink.core.db.models import UserRole
from yoink.core.i18n.loader import t
from yoink_insight.bot.middleware import get_insight_config, get_insight_repo
from yoink_insight.services.gemini import GeminiSummarizer, InsightError

logger = logging.getLogger(__name__)

_YOUTUBE_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+",
    re.IGNORECASE,
)


def _extract_youtube_url(text: str) -> str | None:
    m = _YOUTUBE_RE.search(text)
    return m.group(0) if m else None


def _is_youtube_url(url: str) -> bool:
    host = url.split("/")[2].lstrip("www.") if "://" in url else ""
    return "youtube.com" in host or "youtu.be" in host


@require_access(AccessPolicy(
    min_role=UserRole.user,
    plugin="insight",
    feature="summary",
    scopes=["all"],
    silent_deny=False,
))
async def _cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    repo = get_insight_repo(context)
    config = get_insight_config(context)

    row = await repo.get(user_id)
    lang = row.lang if row else config.insight_default_lang

    args = context.args or []
    url: str | None = None
    if args and _is_youtube_url(args[0]):
        url = args[0]
    if url is None and update.message.text:
        url = _extract_youtube_url(update.message.text)

    if url is None:
        await update.message.reply_html(t("insight.no_url", lang))
        return

    thinking_msg = await update.message.reply_html(t("insight.thinking", lang))

    try:
        summarizer = GeminiSummarizer(config)
        result = await summarizer.describe(url, lang)
        header = t("insight.about_header", lang)
        await thinking_msg.edit_text(f"{header}\n\n{result}", parse_mode="HTML")
    except InsightError as exc:
        key = f"insight.error.{exc.args[0]}" if exc.args else "insight.error.generic"
        err_text = t(key, lang, fallback=t("insight.error.generic", lang))
        await thinking_msg.edit_text(err_text, parse_mode="HTML")


def register(app: Application) -> None:
    app.add_handler(CommandHandler("about", _cmd_about))
