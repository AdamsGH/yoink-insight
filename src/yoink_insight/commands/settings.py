"""/insight_lang - change the AI summary response language for the current user."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from yoink.core.bot.access import AccessPolicy, require_access
from yoink.core.db.models import UserRole
from yoink.core.i18n.loader import t
from yoink_insight.bot.middleware import get_insight_config, get_insight_settings_repo

logger = logging.getLogger(__name__)

_SUPPORTED_LANGS = ["en", "ru", "uk", "de", "fr", "es", "zh", "ja"]

# Only users who have insight/summary access can change the summary language
_FEATURE_POLICY = AccessPolicy(
    min_role=UserRole.user,
    plugin="insight",
    feature="summary",
    scopes=["all"],
    silent_deny=False,
)


def _lang_keyboard(current: str) -> InlineKeyboardMarkup:
    buttons = []
    row: list[InlineKeyboardButton] = []
    for lang in _SUPPORTED_LANGS:
        label = f"[{lang}]" if lang == current else lang
        row.append(InlineKeyboardButton(label, callback_data=f"insight_lang:{lang}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


@require_access(_FEATURE_POLICY)
async def _cmd_insight_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    settings = get_insight_settings_repo(context)
    config = get_insight_config(context)

    current_lang = await settings.get_lang(user_id, default=config.insight_default_lang)

    await update.message.reply_html(
        t("insight_lang.current", current_lang, lang=current_lang),
        reply_markup=_lang_keyboard(current_lang),
    )


async def _cb_insight_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()

    user_id = update.effective_user.id
    lang = (query.data or "").split(":", 1)[-1]
    if lang not in _SUPPORTED_LANGS:
        return

    settings = get_insight_settings_repo(context)
    await settings.set_lang(user_id, lang)

    if query.message:
        await query.edit_message_text(
            t("insight_lang.changed", lang, lang=lang),
            parse_mode="HTML",
        )


def register(app: Application) -> None:
    app.add_handler(CommandHandler("insight_lang", _cmd_insight_lang))
    app.add_handler(CallbackQueryHandler(_cb_insight_lang, pattern=r"^insight_lang:"))
