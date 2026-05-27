"""BYOK as a feature provider for insight:tldr.

When the admin enables `insight_byok_enabled` and a user has saved + probed a
BYOK config, that pair counts as an effective grant for `insight:tldr` even
without a row in `user_permissions`. The provider plugs into
`yoink.core.auth.effective_features` so the runtime gate, the /help section,
and `setMyCommands` all agree.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from yoink.core.db.models import BotSetting

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)

_BYOK_ENABLED_KEY = "insight_byok_enabled"


async def _byok_enabled(session_factory: async_sessionmaker) -> bool:
    async with session_factory() as s:
        row = await s.get(BotSetting, _BYOK_ENABLED_KEY)
        if row is None or not row.value:
            return False
        return row.value.lower() in ("1", "true", "yes", "on")


async def byok_tldr_provider(
    user_id: int,
    session_factory: async_sessionmaker,
    bot_data: dict,
) -> bool:
    """True if BYOK is globally enabled AND this user has a probed config."""
    if not await _byok_enabled(session_factory):
        return False
    repo = bot_data.get("insight_byok_repo")
    if repo is None:
        # Plugin setup hasn't run yet, or the resolver was called outside the
        # bot context. Fall back to a direct query so the API gate still works.
        from yoink_insight.storage.models import InsightUserByok
        async with session_factory() as s:
            row = await s.execute(
                select(InsightUserByok.user_id).where(
                    InsightUserByok.user_id == user_id,
                    InsightUserByok.tested_at.is_not(None),
                    InsightUserByok.test_error.is_(None),
                )
            )
            return row.scalar_one_or_none() is not None
    return await repo.is_ready(user_id)
