"""Insight plugin repositories."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from yoink.core.db.models import User
from yoink_insight.storage.models import InsightAccess, InsightUserSettings


class InsightUserSettingsRepo:
    """CRUD for insight_user_settings (language preferences)."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def get_lang(self, user_id: int, default: str = "en") -> str:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            return row.lang if row is not None else default

    async def set_lang(self, user_id: int, lang: str) -> InsightUserSettings:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            if row is None:
                # Ensure user row exists
                user = await s.get(User, user_id)
                if user is None:
                    user = User(id=user_id)
                    s.add(user)
                    await s.flush()
                row = InsightUserSettings(user_id=user_id, lang=lang)
                s.add(row)
            else:
                row.lang = lang
            await s.commit()
            await s.refresh(row)
            return row


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
        """Update lang in insight_access (legacy) and insight_user_settings."""
        async with self._sf() as s:
            row = await s.get(InsightAccess, user_id)
            if row is not None:
                row.lang = lang
            # Always write to the new settings table
            settings_row = await s.get(InsightUserSettings, user_id)
            if settings_row is None:
                settings_row = InsightUserSettings(user_id=user_id, lang=lang)
                s.add(settings_row)
            else:
                settings_row.lang = lang
            await s.commit()
            if row is not None:
                await s.refresh(row)
            return row
