"""Insight plugin API routes.

Mounted at /api/v1/insight/ by the core API factory.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yoink.core.api.deps import get_current_user, get_db
from yoink.core.api.exceptions import NotFoundError
from yoink.core.auth.rbac import require_role
from yoink.core.db.models import User, UserRole
from yoink_insight.api.schemas import (
    InsightAccessGrant,
    InsightAccessResponse,
    InsightSettingsUpdate,
    InsightUserSettingsResponse,
    UserLookupResult,
)
from yoink_insight.config import InsightConfig
from yoink_insight.storage.models import InsightAccess, InsightUsageLog, InsightUserSettings

router = APIRouter(tags=["insight"], responses={401: {"description": "Not authenticated"}, 403: {"description": "Insufficient role"}})


def _is_owner(user: User) -> bool:
    return user.role == UserRole.owner


def _display(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return user.first_name or str(user.id)


async def _enrich(
    session: AsyncSession, rows: list[InsightAccess]
) -> list[InsightAccessResponse]:
    """Attach username/first_name to a list of InsightAccess rows."""
    all_ids = {r.user_id for r in rows} | {r.granted_by for r in rows}
    users_map: dict[int, User] = {}
    if all_ids:
        result = await session.execute(select(User).where(User.id.in_(all_ids)))
        for u in result.scalars():
            users_map[u.id] = u

    out = []
    for r in rows:
        u = users_map.get(r.user_id)
        g = users_map.get(r.granted_by)
        out.append(InsightAccessResponse(
            user_id=r.user_id,
            lang=r.lang,
            granted_by=r.granted_by,
            granted_at=r.granted_at,
            username=u.username if u else None,
            first_name=u.first_name if u else None,
            granted_by_username=g.username if g else None,
        ))
    return out


async def _get_or_create_owner_row(
    session: AsyncSession, user: User
) -> InsightAccess:
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


@router.get("/access/lookup", response_model=list[UserLookupResult], summary="Search users for access grant (admin+)")
async def lookup_users(
    q: str = Query(..., min_length=1, description="Search query: username or display name (partial match)"),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin, UserRole.owner)),
) -> list[UserLookupResult]:
    """Search users by username or numeric ID. Returns up to 20 results."""
    term = q.lstrip("@")
    stmt = select(User).limit(20)
    if term.isdigit():
        stmt = stmt.where(User.id == int(term))
    else:
        stmt = stmt.where(User.username.ilike(f"%{term}%"))
    result = await session.execute(stmt)
    return [
        UserLookupResult(id=u.id, username=u.username, first_name=u.first_name)
        for u in result.scalars()
    ]


@router.get("/access", response_model=list[InsightAccessResponse], summary="List users with AI summary access (admin+)")
async def list_insight_access(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin, UserRole.owner)),
) -> list[InsightAccessResponse]:
    rows = (
        await session.execute(
            select(InsightAccess).order_by(InsightAccess.granted_at)
        )
    ).scalars().all()
    return await _enrich(session, list(rows))


@router.post("/access/{uid}", response_model=InsightAccessResponse, status_code=201, summary="Grant AI summary access to user (admin+)")
async def grant_insight_access(
    uid: int,
    body: InsightAccessGrant,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.owner)),
) -> InsightAccessResponse:
    db_user = await session.get(User, uid)
    if db_user is None:
        raise NotFoundError(f"User {uid} not found")

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
    enriched = await _enrich(session, [row])
    return enriched[0]


@router.patch("/access/{uid}", response_model=InsightAccessResponse, summary="Update AI summary access settings (admin+)")
async def update_insight_access(
    uid: int,
    body: InsightSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin, UserRole.owner)),
) -> InsightAccessResponse:
    row = await session.get(InsightAccess, uid)
    if row is None:
        raise NotFoundError(f"No insight access entry for user {uid}")
    row.lang = body.lang
    await session.commit()
    await session.refresh(row)
    enriched = await _enrich(session, [row])
    return enriched[0]


@router.delete("/access/{uid}", status_code=204, summary="Revoke AI summary access (admin+)")
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


async def _has_insight_access(session: AsyncSession, user: User) -> bool:
    """Check effective access: owner, user_permissions grant, or legacy insight_access row."""
    from datetime import timezone
    from sqlalchemy import select as sa_select
    from yoink.core.db.models import UserPermission
    if _is_owner(user):
        return True
    now = datetime.now(timezone.utc)
    result = await session.execute(
        sa_select(UserPermission.id).where(
            UserPermission.user_id == user.id,
            UserPermission.plugin == "insight",
            UserPermission.feature == "summary",
            (UserPermission.expires_at.is_(None)) | (UserPermission.expires_at > now),
        )
    )
    if result.scalar_one_or_none() is not None:
        return True
    # Legacy fallback
    legacy = await session.get(InsightAccess, user.id)
    return legacy is not None


@router.get("/me/stats", summary="My AI summary usage stats")
async def get_my_insight_stats(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from datetime import timedelta
    from sqlalchemy import cast, Date, func

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    thirty_days_ago = now - timedelta(days=30)

    base = select(func.count()).select_from(InsightUsageLog).where(
        InsightUsageLog.user_id == current_user.id,
        InsightUsageLog.status == "ok",
    )
    total = (await session.execute(base)).scalar() or 0
    this_week = (await session.execute(
        base.where(InsightUsageLog.created_at >= week_start)
    )).scalar() or 0
    today = (await session.execute(
        base.where(InsightUsageLog.created_at >= today_start)
    )).scalar() or 0

    # By command breakdown
    cmd_rows = (await session.execute(
        select(InsightUsageLog.command, func.count())
        .where(InsightUsageLog.user_id == current_user.id, InsightUsageLog.status == "ok")
        .group_by(InsightUsageLog.command)
    )).all()
    by_command = {row[0]: row[1] for row in cmd_rows}

    # Daily history (last 30 days)
    day_rows = (await session.execute(
        select(
            cast(InsightUsageLog.created_at, Date).label("date"),
            func.count().label("count"),
        )
        .where(
            InsightUsageLog.user_id == current_user.id,
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


@router.get("/settings/me", response_model=InsightUserSettingsResponse, summary="My AI summary settings")
async def get_my_insight_settings(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightUserSettingsResponse:
    has_access = await _has_insight_access(session, current_user)
    config = InsightConfig()
    settings_row = await session.get(InsightUserSettings, current_user.id)
    lang = settings_row.lang if settings_row else config.insight_default_lang
    return InsightUserSettingsResponse(lang=lang, has_access=has_access)


@router.patch("/settings/me", response_model=InsightUserSettingsResponse, summary="Update my AI summary settings", description="Fields: `language` (override summary language, null = use user locale), `detail_level` (`brief`/`detailed`).")
async def update_my_insight_settings(
    body: InsightSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightUserSettingsResponse:
    if not await _has_insight_access(session, current_user):
        raise HTTPException(status_code=403, detail="You do not have Insight access.")

    settings_row = await session.get(InsightUserSettings, current_user.id)
    if settings_row is None:
        settings_row = InsightUserSettings(user_id=current_user.id, lang=body.lang)
        session.add(settings_row)
    else:
        settings_row.lang = body.lang
    await session.commit()
    await session.refresh(settings_row)
    return InsightUserSettingsResponse(lang=settings_row.lang, has_access=True)
