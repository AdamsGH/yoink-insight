"""Insight plugin API routes.

Mounted at /api/v1/insight/ by the core API factory.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from yoink.core.api.deps import get_current_user, get_db
from yoink.core.api.exceptions import NotFoundError
from yoink.core.auth.rbac import require_role
from yoink.core.db.models import User, UserRole
from yoink_insight.config import InsightConfig
from yoink_insight.api.schemas import (
    InsightAccessGrant,
    InsightAccessResponse,
    InsightSettingsUpdate,
)
from yoink_insight.storage.models import InsightAccess

router = APIRouter(tags=["insight"])


@router.get("/access", response_model=list[InsightAccessResponse])
async def list_insight_access(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin, UserRole.owner)),
) -> list[InsightAccessResponse]:
    from sqlalchemy import select

    rows = (
        await session.execute(select(InsightAccess).order_by(InsightAccess.granted_at))
    ).scalars().all()
    return [InsightAccessResponse.model_validate(r) for r in rows]


@router.post("/access/{uid}", response_model=InsightAccessResponse, status_code=201)
async def grant_insight_access(
    uid: int,
    body: InsightAccessGrant,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.owner)),
) -> InsightAccessResponse:
    from yoink.core.db.models import User as CoreUser

    db_user = await session.get(CoreUser, uid)
    if db_user is None:
        db_user = CoreUser(id=uid)
        session.add(db_user)
        await session.flush()

    row = await session.get(InsightAccess, uid)
    if row is None:
        row = InsightAccess(
            user_id=uid,
            lang=body.lang,
            granted_by=current_user.id,
            granted_at=datetime.now(timezone.utc),
        )
        session.add(row)
    else:
        row.lang = body.lang
        row.granted_by = current_user.id
        row.granted_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(row)
    return InsightAccessResponse.model_validate(row)


@router.delete("/access/{uid}", status_code=204)
async def revoke_insight_access(
    uid: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin, UserRole.owner)),
) -> None:
    row = await session.get(InsightAccess, uid)
    if row is None:
        raise NotFoundError(f"No insight access entry for user {uid}")
    await session.delete(row)
    await session.commit()


def _is_owner(user: User) -> bool:
    return user.role == UserRole.owner


async def _get_or_create_owner_row(
    session: AsyncSession, user: User
) -> InsightAccess:
    """Auto-create an insight_access row for owner if one doesn't exist yet."""
    row = await session.get(InsightAccess, user.id)
    if row is None:
        config = InsightConfig()
        row = InsightAccess(
            user_id=user.id,
            lang=config.insight_default_lang,
            granted_by=user.id,
            granted_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


@router.get("/settings/me", response_model=InsightAccessResponse)
async def get_my_insight_settings(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightAccessResponse:
    if _is_owner(current_user):
        row = await _get_or_create_owner_row(session, current_user)
        return InsightAccessResponse.model_validate(row)

    row = await session.get(InsightAccess, current_user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="You do not have Insight access.")
    return InsightAccessResponse.model_validate(row)


@router.patch("/settings/me", response_model=InsightAccessResponse)
async def update_my_insight_settings(
    body: InsightSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightAccessResponse:
    if _is_owner(current_user):
        row = await _get_or_create_owner_row(session, current_user)
    else:
        row = await session.get(InsightAccess, current_user.id)
        if row is None:
            raise HTTPException(status_code=403, detail="You do not have Insight access.")

    row.lang = body.lang
    await session.commit()
    await session.refresh(row)
    return InsightAccessResponse.model_validate(row)
