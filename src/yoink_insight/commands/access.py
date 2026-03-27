"""Admin commands: /insight_grant, /insight_revoke, /insight_list."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from yoink.core.bot.access import AccessPolicy, require_access
from yoink.core.db.models import UserRole
from yoink.core.i18n.loader import t
from yoink_insight.bot.middleware import get_insight_access, get_insight_config

logger = logging.getLogger(__name__)

_ADMIN_POLICY = AccessPolicy(min_role=UserRole.admin, scopes=["all"], silent_deny=True)

_PAGE_SIZE = 20


@require_access(_ADMIN_POLICY)
async def _cmd_insight_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Grant insight access: /insight_grant <user_id> [lang]"""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_html(
            "Usage: <code>/insight_grant &lt;user_id&gt; [lang]</code>"
        )
        return

    user_id = int(args[0])
    config = get_insight_config(context)
    lang = args[1] if len(args) > 1 else config.insight_default_lang

    access = get_insight_access(context)
    await access.grant(user_id, granted_by=update.effective_user.id, lang=lang)

    await update.message.reply_html(
        t("insight_access.granted", "en", user_id=user_id, lang=lang)
    )


@require_access(_ADMIN_POLICY)
async def _cmd_insight_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoke insight access: /insight_revoke <user_id>"""
    if not update.message:
        return

    args = context.args or []
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_html(
            "Usage: <code>/insight_revoke &lt;user_id&gt;</code>"
        )
        return

    user_id = int(args[0])
    access = get_insight_access(context)
    removed = await access.revoke(user_id)

    if removed:
        await update.message.reply_html(
            t("insight_access.revoked", "en", user_id=user_id)
        )
    else:
        await update.message.reply_html(
            t("insight_access.not_found", "en", user_id=user_id)
        )


@require_access(_ADMIN_POLICY)
async def _cmd_insight_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/insight_list - paginated list of users with insight access."""
    if not update.message:
        return

    access = get_insight_access(context)
    rows = await access.list_all()

    if not rows:
        await update.message.reply_html(t("insight_access.list_empty", "en"))
        return

    header = t("insight_access.list_header", "en")
    lines = [header]
    for row in rows:
        lines.append(
            t(
                "insight_access.list_item",
                "en",
                user_id=row.user_id,
                lang=row.lang,
                granted_by=row.granted_by,
            )
        )

    text = "\n".join(lines)
    # Chunk if too long
    for chunk in [text[i: i + 4000] for i in range(0, len(text), 4000)]:
        await update.message.reply_html(chunk)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("insight_grant", _cmd_insight_grant))
    app.add_handler(CommandHandler("insight_revoke", _cmd_insight_revoke))
    app.add_handler(CommandHandler("insight_list", _cmd_insight_list))
