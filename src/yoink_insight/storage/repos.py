"""Insight plugin repositories."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from yoink.core.db.models import User
from yoink_insight.storage.models import InsightAccess


class InsightAccessRepo:
    """CRUD for the insight_access allowlist table."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def get(self, user_id: int) -> InsightAccess | None:
        async with self._sf() as s:
            return await s.get(InsightAccess, user_id)

    async def grant(
        self,
        user_id: int,
        granted_by: int,
        lang: str = "en",
    ) -> InsightAccess:
        """Upsert an access row. Creates User if it does not exist yet."""
        async with self._sf() as s:
            user = await s.get(User, user_id)
            if user is None:
                user = User(id=user_id)
                s.add(user)
                await s.flush()

            row = await s.get(InsightAccess, user_id)
            if row is None:
                row = InsightAccess(
                    user_id=user_id,
                    granted_by=granted_by,
                    lang=lang,
                    granted_at=datetime.now(timezone.utc),
                )
                s.add(row)
            else:
                row.granted_by = granted_by
                row.lang = lang
                row.granted_at = datetime.now(timezone.utc)
            await s.commit()
            await s.refresh(row)
            return row

    async def revoke(self, user_id: int) -> bool:
        async with self._sf() as s:
            result = await s.execute(
                delete(InsightAccess).where(InsightAccess.user_id == user_id)
            )
            await s.commit()
            return result.rowcount > 0

    async def list_all(self) -> list[InsightAccess]:
        async with self._sf() as s:
            result = await s.execute(
                select(InsightAccess).order_by(InsightAccess.granted_at)
            )
            return list(result.scalars().all())

    async def get_lang(self, user_id: int, default: str = "en") -> str:
        row = await self.get(user_id)
        return row.lang if row is not None else default

    async def update_lang(self, user_id: int, lang: str) -> InsightAccess | None:
        async with self._sf() as s:
            row = await s.get(InsightAccess, user_id)
            if row is None:
                return None
            row.lang = lang
            await s.commit()
            await s.refresh(row)
            return row
