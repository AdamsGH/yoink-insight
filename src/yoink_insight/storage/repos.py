"""Insight plugin repositories."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from yoink.core.db.models import User
from yoink_insight.storage.models import InsightAccess, InsightUsageLog, InsightUserSettings


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


class InsightUsageLogRepo:
    """Write/query insight_usage_log entries."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def log(
        self,
        user_id: int,
        command: str,
        *,
        video_id: str | None = None,
        lang: str = "en",
        status: str = "ok",
        error_code: str | None = None,
    ) -> None:
        async with self._sf() as s:
            s.add(InsightUsageLog(
                user_id=user_id,
                command=command,
                video_id=video_id,
                lang=lang,
                status=status,
                error_code=error_code,
            ))
            await s.commit()

    async def stats_for_user(self, user_id: int) -> dict:
        """Return aggregate stats for a single user."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - __import__("datetime").timedelta(days=today_start.weekday())

        async with self._sf() as s:
            base = select(func.count()).select_from(InsightUsageLog).where(
                InsightUsageLog.user_id == user_id,
                InsightUsageLog.status == "ok",
            )
            total = (await s.execute(base)).scalar() or 0
            this_week = (await s.execute(
                base.where(InsightUsageLog.created_at >= week_start)
            )).scalar() or 0
            today = (await s.execute(
                base.where(InsightUsageLog.created_at >= today_start)
            )).scalar() or 0

            # By command breakdown
            cmd_rows = (await s.execute(
                select(InsightUsageLog.command, func.count())
                .where(InsightUsageLog.user_id == user_id, InsightUsageLog.status == "ok")
                .group_by(InsightUsageLog.command)
            )).all()
            by_command = {row[0]: row[1] for row in cmd_rows}

            # Daily history (last 30 days)
            from sqlalchemy import cast, Date
            thirty_days_ago = now - __import__("datetime").timedelta(days=30)
            day_rows = (await s.execute(
                select(
                    cast(InsightUsageLog.created_at, Date).label("date"),
                    func.count().label("count"),
                )
                .where(
                    InsightUsageLog.user_id == user_id,
                    InsightUsageLog.status == "ok",
                    InsightUsageLog.created_at >= thirty_days_ago,
                )
                .group_by("date")
                .order_by("date")
            )).all()
            by_day = [{"date": str(row[0]), "count": row[1]} for row in day_rows]

        return {
            "total_summaries": total,
            "this_week": this_week,
            "today": today,
            "by_command": by_command,
            "by_day": by_day,
        }
