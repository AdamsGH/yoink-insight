"""/summary <url> - summarize a YouTube video as bullet points."""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from yoink.core.bot.access import AccessPolicy, require_access
from yoink.core.db.models import UserRole
from yoink.core.i18n.loader import t
from yoink_insight.bot.middleware import get_insight_config, get_insight_settings_repo, get_insight_usage_repo
from yoink_insight.commands._runner import run_insight_command
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
    group_silent_deny=True,
))
async def _cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    settings = get_insight_settings_repo(context)
    config = get_insight_config(context)
    lang = await settings.get_lang(user_id, default=config.insight_default_lang)

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

    cache_repo = context.bot_data.get("insight_summary_cache")
    usage_repo = get_insight_usage_repo(context)

    try:
        summarizer = GeminiSummarizer(config)
    except InsightError as exc:
        key = f"insight.error.{exc.args[0]}" if exc.args else "insight.error.generic"
        await thinking_msg.edit_text(
            t(key, lang, fallback=t("insight.error.generic", lang)),
            parse_mode="HTML",
        )
        return

    await run_insight_command(
        command="summary",
        url=url,
        lang=lang,
        thinking_msg=thinking_msg,
        header=t("insight.summary_header", lang),
        summarizer=summarizer,
        cache_repo=cache_repo,
        usage_repo=usage_repo,
        user_id=user_id,
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler("summary", _cmd_summary))
