"""Insight plugin middleware helpers."""
from __future__ import annotations

from telegram.ext import ContextTypes

from yoink_insight.config import InsightConfig
from yoink_insight.storage.repos import InsightAccessRepo


def get_insight_config(context: ContextTypes.DEFAULT_TYPE) -> InsightConfig:
    return context.bot_data["insight_config"]


def get_insight_repo(context: ContextTypes.DEFAULT_TYPE) -> InsightAccessRepo:
    return context.bot_data["insight_repo"]


def get_owner_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.bot_data["config"].owner_id
