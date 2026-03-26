"""InsightAccessService - thin wrapper combining owner bypass and repo operations."""
from __future__ import annotations

from yoink_insight.storage.models import InsightAccess
from yoink_insight.storage.repos import InsightAccessRepo


class InsightAccessService:
    """Checks whether a user is allowed to use Insight features.

    The bot owner always passes, regardless of allowlist state.
    Everyone else must have an InsightAccess row.
    """

    def __init__(self, repo: InsightAccessRepo, owner_id: int) -> None:
        self._repo = repo
        self._owner_id = owner_id

    async def is_allowed(self, user_id: int) -> bool:
        if user_id == self._owner_id:
            return True
        row = await self._repo.get(user_id)
        return row is not None

    async def grant(
        self, user_id: int, granted_by: int, lang: str = "en"
    ) -> InsightAccess:
        return await self._repo.grant(user_id, granted_by=granted_by, lang=lang)

    async def revoke(self, user_id: int) -> bool:
        return await self._repo.revoke(user_id)

    async def list_all(self) -> list[InsightAccess]:
        return await self._repo.list_all()
