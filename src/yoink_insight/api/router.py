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
    TldrConfigResponse,
    TldrConfigUpdate,
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


async def _has_feature_access(session: AsyncSession, user: User, feature: str) -> bool:
    """Check effective access for any insight plugin feature."""
    if _is_owner(user):
        return True
    now = datetime.now(timezone.utc)
    from sqlalchemy import select as sa_select
    from yoink.core.db.models import UserPermission
    result = await session.execute(
        sa_select(UserPermission.id).where(
            UserPermission.user_id == user.id,
            UserPermission.plugin == "insight",
            UserPermission.feature == feature,
            (UserPermission.expires_at.is_(None)) | (UserPermission.expires_at > now),
        )
    )
    return result.scalar_one_or_none() is not None


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
    has_tldr = await _has_feature_access(session, current_user, "tldr")
    config = InsightConfig()
    settings_row = await session.get(InsightUserSettings, current_user.id)
    lang = settings_row.lang if settings_row else config.insight_default_lang
    tldr_model = settings_row.tldr_model if settings_row else None
    github_token = settings_row.github_token if settings_row else None
    allowed = await _get_tldr_allowed_models_from_db(session, config)
    return InsightUserSettingsResponse(
        lang=lang,
        has_access=has_access,
        has_tldr_access=has_tldr,
        tldr_model=tldr_model,
        tldr_allowed_models=allowed if has_tldr else [],
        github_token_set=bool(github_token),
    )


@router.patch("/settings/me", response_model=InsightUserSettingsResponse, summary="Update my AI summary settings")
async def update_my_insight_settings(
    body: InsightSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightUserSettingsResponse:
    has_access = await _has_insight_access(session, current_user)
    has_tldr = await _has_feature_access(session, current_user, "tldr")
    if not has_access and not has_tldr:
        raise HTTPException(status_code=403, detail="You do not have Insight access.")

    config = InsightConfig()

    # Validate tldr_model against allowed list (owner bypasses)
    tldr_model = body.tldr_model
    if tldr_model is not None and not _is_owner(current_user):
        allowed = await _get_tldr_allowed_models_from_db(session, config)
        if tldr_model not in allowed:
            raise HTTPException(status_code=400, detail=f"Model '{tldr_model}' is not in the allowed list.")

    settings_row = await session.get(InsightUserSettings, current_user.id)
    if settings_row is None:
        settings_row = InsightUserSettings(
            user_id=current_user.id,
            lang=body.lang,
            tldr_model=tldr_model,
            github_token=body.github_token,
        )
        session.add(settings_row)
    else:
        settings_row.lang = body.lang
        if tldr_model is not None or body.tldr_model is not None:
            settings_row.tldr_model = tldr_model
        if body.github_token is not None:
            settings_row.github_token = body.github_token or None
    await session.commit()
    await session.refresh(settings_row)
    allowed = await _get_tldr_allowed_models_from_db(session, config)
    return InsightUserSettingsResponse(
        lang=settings_row.lang,
        has_access=has_access,
        has_tldr_access=has_tldr,
        tldr_model=settings_row.tldr_model,
        tldr_allowed_models=allowed if has_tldr else [],
        github_token_set=bool(settings_row.github_token),
    )


# --- TLDR config (admin/owner) ---

_TLDR_ALLOWED_KEY = "insight_tldr_allowed_models"
_TLDR_DEFAULT_KEY = "insight_tldr_default_model"
_TLDR_GW_URL_KEY = "insight_tldr_gateway_url"
_TLDR_GW_KEY_KEY = "insight_tldr_gateway_key"


async def _get_tldr_allowed_models_from_db(session: AsyncSession, config: InsightConfig) -> list[str]:
    """Load allowed_models from bot_settings, fall back to [default_model]."""
    import json
    from yoink.core.db.models import BotSetting
    row = await session.get(BotSetting, _TLDR_ALLOWED_KEY)
    if row and row.value:
        try:
            val = json.loads(row.value)
            if isinstance(val, list):
                return val
        except Exception:
            pass
    return [config.tldr_llm_model]


async def _get_tldr_default_model_from_db(session: AsyncSession, config: InsightConfig) -> str:
    from yoink.core.db.models import BotSetting
    row = await session.get(BotSetting, _TLDR_DEFAULT_KEY)
    if row and row.value:
        return row.value
    return config.tldr_llm_model


@router.get("/config/tldr", response_model=TldrConfigResponse, summary="Get TLDR model config (admin+)")
async def get_tldr_config(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin, UserRole.owner)),
) -> TldrConfigResponse:
    from yoink.core.db.models import BotSetting
    config = InsightConfig()
    allowed = await _get_tldr_allowed_models_from_db(session, config)
    default = await _get_tldr_default_model_from_db(session, config)
    gw_url_row = await session.get(BotSetting, _TLDR_GW_URL_KEY)
    gw_key_row = await session.get(BotSetting, _TLDR_GW_KEY_KEY)
    return TldrConfigResponse(
        allowed_models=allowed,
        default_model=default,
        gateway_base_url=(gw_url_row.value if gw_url_row is not None else None) or config.gateway_base_url,
        gateway_api_key=(gw_key_row.value if gw_key_row is not None else None) or "",
    )


@router.patch("/config/tldr", response_model=TldrConfigResponse, summary="Update TLDR model config (admin+)")
async def update_tldr_config(
    body: TldrConfigUpdate,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin, UserRole.owner)),
) -> TldrConfigResponse:
    import json
    from yoink.core.db.models import BotSetting
    if not body.allowed_models:
        raise HTTPException(status_code=400, detail="allowed_models must not be empty.")
    if body.default_model not in body.allowed_models:
        raise HTTPException(status_code=400, detail="default_model must be in allowed_models.")

    for key, value in [
        (_TLDR_ALLOWED_KEY, json.dumps(body.allowed_models)),
        (_TLDR_DEFAULT_KEY, body.default_model),
        (_TLDR_GW_URL_KEY, body.gateway_base_url.rstrip("/")),
        (_TLDR_GW_KEY_KEY, body.gateway_api_key),
    ]:
        row = await session.get(BotSetting, key)
        if row is None:
            session.add(BotSetting(key=key, value=value))
        else:
            row.value = value
    await session.commit()
    return TldrConfigResponse(
        allowed_models=body.allowed_models,
        default_model=body.default_model,
        gateway_base_url=body.gateway_base_url.rstrip("/"),
        gateway_api_key=body.gateway_api_key,
    )


@router.get("/models", summary="List available LLM models for TLDR")
async def list_tldr_models(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Owner sees all gateway models (via stored gateway URL); others see the allowed list."""
    config = InsightConfig()
    if _is_owner(current_user):
        gw_url, gw_key = await _get_gateway_settings(session, config)
        return await _fetch_gateway_models(gw_url, gw_key, config)
    allowed = await _get_tldr_allowed_models_from_db(session, config)
    return [{"id": m} for m in allowed]


@router.get("/config/test", summary="Test gateway connectivity (admin+)")
async def test_gateway(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin, UserRole.owner)),
    url: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Probe gateway /v1/models. Uses provided url/api_key if given, else falls back to bot_settings."""
    import httpx
    config = InsightConfig()
    if url:
        gw_url, gw_key = url.rstrip("/"), api_key or ""
    else:
        gw_url, gw_key = await _get_gateway_settings(session, config)
    endpoint = gw_url.rstrip("/") + "/v1/models"
    headers: dict[str, str] = {}
    if gw_key:
        headers["Authorization"] = f"Bearer {gw_key}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(endpoint, headers=headers)
        if resp.status_code == 200:
            models = resp.json().get("data", [])
            return {"ok": True, "model_count": len(models), "url": gw_url}
        return {"ok": False, "error": f"HTTP {resp.status_code}", "url": gw_url}
    except httpx.ConnectError:
        return {"ok": False, "error": "Connection refused", "url": gw_url}
    except httpx.TimeoutException:
        return {"ok": False, "error": "Timeout", "url": gw_url}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": gw_url}


async def _get_gateway_settings(session: AsyncSession, config: InsightConfig) -> tuple[str, str]:
    """Return (gateway_base_url, gateway_api_key) from bot_settings, falling back to InsightConfig."""
    from yoink.core.db.models import BotSetting
    gw_url_row = await session.get(BotSetting, _TLDR_GW_URL_KEY)
    gw_key_row = await session.get(BotSetting, _TLDR_GW_KEY_KEY)
    gw_url = (gw_url_row.value if gw_url_row is not None else None) or config.gateway_base_url
    gw_key = (gw_key_row.value if gw_key_row is not None else None) or config.gateway_api_key
    return gw_url, gw_key


async def _fetch_gateway_models(gw_url: str, gw_key: str, config: InsightConfig) -> list[dict]:
    import httpx
    endpoint = gw_url.rstrip("/") + "/v1/models"
    headers: dict[str, str] = {}
    if gw_key:
        headers["Authorization"] = f"Bearer {gw_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(endpoint, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", [])
    except Exception:
        pass
    return [{"id": config.tldr_llm_model}]
