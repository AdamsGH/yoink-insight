"""/summary <url> - summarize a YouTube video as bullet points."""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from yoink.core.bot.access import AccessPolicy, require_access
from yoink.core.db.models import UserRole
from yoink.core.i18n.loader import t
from yoink_insight.bot.middleware import get_insight_config, get_insight_repo, get_owner_id
from yoink_insight.services.gemini import GeminiError, GeminiRunner

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = (
    "Watch this YouTube video and summarize its key points as a bullet list.\n"
    "Be concise. Reply in {lang}.\n\n"
    "{url}"
)

_YOUTUBE_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+",
    re.IGNORECASE,
)


def _extract_youtube_url(text: str) -> str | None:
    m = _YOUTUBE_RE.search(text)
    return m.group(0) if m else None


def _is_youtube_url(url: str) -> bool:
    parsed_host = url.split("/")[2].lstrip("www.") if "://" in url else ""
    return "youtube.com" in parsed_host or "youtu.be" in parsed_host


@require_access(AccessPolicy(min_role=UserRole.user, scopes=["all"], silent_deny=False))
async def _cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    lang = update.message.from_user.language_code or "en"

    repo = get_insight_repo(context)
    owner_id = get_owner_id(context)
    config = get_insight_config(context)

    # Check insight-specific allowlist (separate from RBAC min_role check above)
    if user_id != owner_id:
        row = await repo.get(user_id)
        if row is None:
            await update.message.reply_html(t("insight.no_access", lang))
            return
        lang = row.lang
    else:
        row = await repo.get(user_id)
        if row is not None:
            lang = row.lang
        else:
            lang = config.insight_default_lang

    # Resolve URL from args or message text
    args = context.args or []
    url: str | None = None
    if args:
        candidate = args[0]
        if _is_youtube_url(candidate):
            url = candidate
    if url is None and update.message.text:
        url = _extract_youtube_url(update.message.text)

    if url is None:
        await update.message.reply_html(t("insight.no_url", lang))
        return

    if not _is_youtube_url(url):
        await update.message.reply_html(t("insight.not_youtube", lang))
        return

    thinking_msg = await update.message.reply_html(t("insight.thinking", lang))

    prompt = SUMMARY_PROMPT.format(url=url, lang=lang)
    runner = GeminiRunner(config)
    try:
        result = await runner.run(prompt)
        header = t("insight.summary_header", lang)
        await thinking_msg.edit_text(f"{header}\n\n{result}", parse_mode="HTML")
    except GeminiError as exc:
        err_text = t("insight.error", lang, error=str(exc))
        await thinking_msg.edit_text(err_text, parse_mode="HTML")


def register(app: Application) -> None:
    app.add_handler(CommandHandler("summary", _cmd_summary))
