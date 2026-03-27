"""InsightAccessService - access check via unified user_permissions table.

InsightAccess (insight_access table) is kept as a legacy fallback during
transition. New grants go to user_permissions only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from yoink.core.db.models import User, UserPermission
from yoink_insight.storage.models import InsightAccess
from yoink_insight.storage.repos import InsightAccessRepo

_PLUGIN = "insight"
_FEATURE = "summary"


class InsightAccessService:
    """Checks whether a user is allowed to use Insight features.

    Check order:
    1. Owner always passes.
    2. user_permissions row (plugin="insight", feature="summary") - primary path.
    3. Legacy insight_access row - fallback for rows not yet migrated.
    """

    def __init__(
        self,
        repo: InsightAccessRepo,
        owner_id: int,
        session_factory: async_sessionmaker,
    ) -> None:
        self._repo = repo
        self._owner_id = owner_id
        self._sf = session_factory

    async def is_allowed(self, user_id: int) -> bool:
        if user_id == self._owner_id:
            return True

        now = datetime.now(timezone.utc)
        async with self._sf() as s:
            # Primary: unified permissions table
            perm = await s.execute(
                select(UserPermission.id).where(
                    UserPermission.user_id == user_id,
                    UserPermission.plugin == _PLUGIN,
                    UserPermission.feature == _FEATURE,
                    (UserPermission.expires_at.is_(None))
                    | (UserPermission.expires_at > now),
                )
            )
            if perm.scalar_one_or_none() is not None:
                return True

            # Legacy fallback
            legacy = await s.get(InsightAccess, user_id)
            return legacy is not None

    async def grant(
        self,
        user_id: int,
        granted_by: int,
        lang: str = "en",
    ) -> UserPermission:
        """Grant insight/summary in user_permissions. Also upserts legacy insight_access."""
        now = datetime.now(timezone.utc)
        async with self._sf() as s:
            user = await s.get(User, user_id)
            if user is None:
                user = User(id=user_id)
                s.add(user)
                await s.flush()

            result = await s.execute(
                select(UserPermission).where(
                    UserPermission.user_id == user_id,
                    UserPermission.plugin == _PLUGIN,
                    UserPermission.feature == _FEATURE,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = UserPermission(
                    user_id=user_id,
                    plugin=_PLUGIN,
                    feature=_FEATURE,
                    granted_by=granted_by,
                    granted_at=now,
                )
                s.add(row)
            else:
                row.granted_by = granted_by
                row.granted_at = now
                row.expires_at = None
            await s.commit()
            await s.refresh(row)
            return row

    async def revoke(self, user_id: int) -> bool:
        """Revoke from both user_permissions and legacy insight_access."""
        async with self._sf() as s:
            perm_result = await s.execute(
                delete(UserPermission).where(
                    UserPermission.user_id == user_id,
                    UserPermission.plugin == _PLUGIN,
                    UserPermission.feature == _FEATURE,
                )
            )
            legacy_result = await s.execute(
                delete(InsightAccess).where(InsightAccess.user_id == user_id)
            )
            await s.commit()
            return (perm_result.rowcount + legacy_result.rowcount) > 0

    async def list_all(self) -> list[InsightAccess]:
        """Legacy list - returns insight_access rows for backward compat with old API."""
        return await self._repo.list_all()
