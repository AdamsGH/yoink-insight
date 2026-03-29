"""Activity provider for the insight plugin."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yoink.core.activity import PluginActivity


async def insight_activity_provider(session: AsyncSession, user_id: int) -> PluginActivity:
    from yoink_insight.storage.models import InsightUsageLog  # noqa: PLC0415

    base = InsightUsageLog.user_id == user_id
    total = (await session.execute(
        select(func.count()).select_from(InsightUsageLog).where(base)
    )).scalar_one()
    last_at = (await session.execute(
        select(func.max(InsightUsageLog.created_at)).where(base)
    )).scalar_one()

    return PluginActivity(plugin="insight", total=total, last_at=last_at, extra={})
