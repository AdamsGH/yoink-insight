"""/insight_lang - change the response language for the current user."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from yoink.core.bot.access import AccessPolicy, require_access
from yoink.core.db.models import UserRole
from yoink.core.i18n.loader import t
from yoink_insight.bot.middleware import get_insight_access, get_insight_repo, get_owner_id

logger = logging.getLogger(__name__)

_SUPPORTED_LANGS = ["en", "ru", "uk", "de", "fr", "es", "zh", "ja"]

_USER_POLICY = AccessPolicy(min_role=UserRole.user, scopes=["all"], silent_deny=False)


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


@require_access(_USER_POLICY)
async def _cmd_insight_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    access = get_insight_access(context)
    repo = get_insight_repo(context)
    owner_id = get_owner_id(context)

    if not await access.is_allowed(user_id):
        await update.message.reply_html(t("insight_lang.no_access", "en"))
        return

    row = await repo.get(user_id)
    current_lang = row.lang if row is not None else "en"

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

    access = get_insight_access(context)
    repo = get_insight_repo(context)
    owner_id = get_owner_id(context)

    if not await access.is_allowed(user_id):
        await query.edit_message_text(t("insight_lang.no_access", "en"))
        return

    updated = await repo.update_lang(user_id, lang)
    if updated is None and user_id == owner_id:
        # Owner without a row: nothing to update, just acknowledge
        pass

    if query.message:
        await query.edit_message_text(
            t("insight_lang.changed", lang, lang=lang),
            parse_mode="HTML",
        )


def register(app: Application) -> None:
    app.add_handler(CommandHandler("insight_lang", _cmd_insight_lang))
    app.add_handler(CallbackQueryHandler(_cb_insight_lang, pattern=r"^insight_lang:"))
