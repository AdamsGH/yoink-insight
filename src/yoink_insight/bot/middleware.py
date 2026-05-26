"""Insight plugin middleware helpers."""
from __future__ import annotations

from telegram.ext import ContextTypes

from yoink_insight.config import InsightConfig
from yoink_insight.services.access import InsightAccessService
from yoink_insight.storage.repos import (
    InsightAccessRepo,
    InsightUsageLogRepo,
    InsightUserByokRepo,
    InsightUserPromptRepo,
    InsightUserSettingsRepo,
)


def get_insight_config(context: ContextTypes.DEFAULT_TYPE) -> InsightConfig:
    return context.bot_data["insight_config"]


def get_insight_repo(context: ContextTypes.DEFAULT_TYPE) -> InsightAccessRepo:
    return context.bot_data["insight_repo"]


def get_insight_access(context: ContextTypes.DEFAULT_TYPE) -> InsightAccessService:
    return context.bot_data["insight_access"]


def get_insight_settings_repo(context: ContextTypes.DEFAULT_TYPE) -> InsightUserSettingsRepo:
    return context.bot_data["insight_settings_repo"]


def get_insight_usage_repo(context: ContextTypes.DEFAULT_TYPE) -> InsightUsageLogRepo:
    return context.bot_data["insight_usage_repo"]


def get_insight_prompts_repo(context: ContextTypes.DEFAULT_TYPE) -> InsightUserPromptRepo:
    return context.bot_data["insight_prompts_repo"]


def get_insight_byok_repo(context: ContextTypes.DEFAULT_TYPE) -> InsightUserByokRepo:
    return context.bot_data["insight_byok_repo"]


async def is_byok_enabled(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Read the global insight_byok_enabled tumbler from bot_settings."""
    repo = context.bot_data.get("bot_settings_repo")
    if repo is None:
        return False
    raw = await repo.get("insight_byok_enabled")
    if not raw:
        return False
    return raw.lower() in ("1", "true", "yes", "on")


def get_owner_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.bot_data["config"].owner_id


async def get_effective_insight_config(context: ContextTypes.DEFAULT_TYPE) -> InsightConfig:
    """Return InsightConfig with gateway/model settings overridden from bot_settings."""
    import copy
    config = context.bot_data["insight_config"]
    repo = context.bot_data.get("bot_settings_repo")
    if repo is None:
        return config
    gw_url = await repo.get("insight_tldr_gateway_url") or config.gateway_base_url
    gw_key = await repo.get("insight_tldr_gateway_key") or config.gateway_api_key
    default_model = await repo.get("insight_tldr_default_model") or config.tldr_llm_model
    cfg = copy.copy(config)
    cfg.gateway_base_url = gw_url
    cfg.gateway_api_key = gw_key
    cfg.tldr_llm_model = default_model
    return cfg
