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
    TldrAliasCreate,
    TldrAliasResponse,
    TldrAliasUpdate,
    TldrConfigResponse,
    TldrConfigUpdate,
    UserLookupResult,
)
from yoink_insight.config import InsightConfig
from yoink_insight.storage.models import (
    InsightAccess,
    InsightTldrAlias,
    InsightUsageLog,
    InsightUserPrompt,
    InsightUserSettings,
)

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


# Reading-time heuristics for /me/stats time-saved.
#
# Web pages: ~200 wpm * ~5 chars/word -> 1000 chars/min.
#   minutes_saved = content_chars / _CHARS_PER_MINUTE_WEB
# YouTube without duration: fall back to transcript word count / 150 wpm.
#   transcript_word_count ~= content_chars / _AVG_WORD_LEN
_CHARS_PER_MINUTE_WEB = 1000
_AVG_WORD_LEN = 5.5
_TRANSCRIPT_WPM = 150


def _minutes_saved_for_row(video_seconds: int | None, content_chars: int | None, is_youtube: bool) -> float:
    """Return minutes-saved estimate for a single tldr usage row."""
    if video_seconds and video_seconds > 0:
        return video_seconds / 60.0
    if not content_chars or content_chars <= 0:
        return 0.0
    if is_youtube:
        words = content_chars / _AVG_WORD_LEN
        return words / _TRANSCRIPT_WPM
    return content_chars / _CHARS_PER_MINUTE_WEB


@router.get("/me/stats", summary="My AI summary usage stats")
async def get_my_insight_stats(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from datetime import timedelta
    from sqlalchemy import cast, Date, func, or_

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

    # By command breakdown. Collapse 'tldr:<alias>' rows into 'tldr' so the
    # AI Summaries card stays readable; per-alias detail lives in the tldr block.
    cmd_rows = (await session.execute(
        select(InsightUsageLog.command, func.count())
        .where(InsightUsageLog.user_id == current_user.id, InsightUsageLog.status == "ok")
        .group_by(InsightUsageLog.command)
    )).all()
    by_command: dict[str, int] = {}
    for row in cmd_rows:
        bucket = "tldr" if (row[0] or "").startswith("tldr") else row[0]
        by_command[bucket] = by_command.get(bucket, 0) + row[1]

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

    # TLDR-specific block: counters, by_alias, by_kind, by_day with minutes_saved.
    tldr_filter = or_(
        InsightUsageLog.command == "tldr",
        InsightUsageLog.command.like("tldr:%"),
    )
    ok_or_cached = InsightUsageLog.status.in_(("ok", "cached"))
    tldr_base = select(func.count()).select_from(InsightUsageLog).where(
        InsightUsageLog.user_id == current_user.id,
        tldr_filter,
        ok_or_cached,
    )
    tldr_total = (await session.execute(tldr_base)).scalar() or 0
    tldr_week = (await session.execute(
        tldr_base.where(InsightUsageLog.created_at >= week_start)
    )).scalar() or 0
    tldr_today = (await session.execute(
        tldr_base.where(InsightUsageLog.created_at >= today_start)
    )).scalar() or 0

    alias_rows = (await session.execute(
        select(InsightUsageLog.alias_key, func.count())
        .where(
            InsightUsageLog.user_id == current_user.id,
            tldr_filter,
            ok_or_cached,
        )
        .group_by(InsightUsageLog.alias_key)
    )).all()
    tldr_by_alias = [
        {"alias": row[0] or "_none", "count": row[1]}
        for row in alias_rows
    ]
    tldr_by_alias.sort(key=lambda r: r["count"], reverse=True)

    yt_count = (await session.execute(
        tldr_base.where(InsightUsageLog.video_seconds.is_not(None))
    )).scalar() or 0
    web_count = tldr_total - yt_count

    # Iterate per-row to compute minutes_saved deterministically across the
    # heuristics (cheap: row count is bounded by tldr usage, not by all events).
    detail_rows = (await session.execute(
        select(
            cast(InsightUsageLog.created_at, Date).label("date"),
            InsightUsageLog.video_seconds,
            InsightUsageLog.content_chars,
            InsightUsageLog.alias_key,
        ).where(
            InsightUsageLog.user_id == current_user.id,
            tldr_filter,
            ok_or_cached,
            InsightUsageLog.created_at >= thirty_days_ago,
        )
    )).all()

    tldr_by_day_map: dict[str, dict] = {}
    video_minutes_saved = 0.0
    reading_minutes_saved = 0.0
    for d, v_sec, c_chars, alias_key in detail_rows:
        is_yt = v_sec is not None
        minutes = _minutes_saved_for_row(v_sec, c_chars, is_yt)
        if is_yt:
            video_minutes_saved += minutes
        else:
            reading_minutes_saved += minutes
        bucket = tldr_by_day_map.setdefault(str(d), {"count": 0, "minutes_saved": 0.0, "by_alias": {}})
        bucket["count"] += 1
        bucket["minutes_saved"] += minutes
        alias_bucket = alias_key or "_none"
        bucket["by_alias"][alias_bucket] = bucket["by_alias"].get(alias_bucket, 0) + 1

    tldr_by_day = [
        {
            "date": k,
            "count": int(v["count"]),
            "minutes_saved": round(v["minutes_saved"], 1),
            "by_alias": v["by_alias"],
        }
        for k, v in sorted(tldr_by_day_map.items())
    ]

    # Totals across all-time (not just 30d) for the top-level minutes_saved counter.
    all_rows = (await session.execute(
        select(
            InsightUsageLog.video_seconds,
            InsightUsageLog.content_chars,
        ).where(
            InsightUsageLog.user_id == current_user.id,
            tldr_filter,
            ok_or_cached,
        )
    )).all()
    all_video_minutes = 0.0
    all_reading_minutes = 0.0
    for v_sec, c_chars in all_rows:
        is_yt = v_sec is not None
        minutes = _minutes_saved_for_row(v_sec, c_chars, is_yt)
        if is_yt:
            all_video_minutes += minutes
        else:
            all_reading_minutes += minutes

    tldr_block = {
        "total": tldr_total,
        "this_week": tldr_week,
        "today": tldr_today,
        "by_alias": tldr_by_alias,
        "by_kind": {"youtube": yt_count, "web": web_count},
        "by_day": tldr_by_day,
        "minutes_saved": round(all_video_minutes + all_reading_minutes, 1),
        "video_minutes_saved": round(all_video_minutes, 1),
        "reading_minutes_saved": round(all_reading_minutes, 1),
    }

    return {
        "total_summaries": total,
        "this_week": this_week,
        "today": today,
        "by_command": by_command,
        "by_day": by_day,
        "tldr": tldr_block,
    }


_BUILTIN_PROMPT_DEFAULTS_CACHE: dict[str, str] | None = None
_BUILTIN_ALIAS_DEFAULTS_CACHE: dict[str, str] | None = None


def _get_builtin_prompt_defaults() -> dict[str, str]:
    """Return the built-in prompt instructions for {summary, about, tldr}.

    Cached after first call (defaults are module-level constants).
    """
    global _BUILTIN_PROMPT_DEFAULTS_CACHE
    if _BUILTIN_PROMPT_DEFAULTS_CACHE is None:
        from yoink_insight.services.gemini import ABOUT_INSTRUCTION, SUMMARY_INSTRUCTION
        from yoink_insight.services.tldr import TLDR_INSTRUCTION
        _BUILTIN_PROMPT_DEFAULTS_CACHE = {
            "summary": SUMMARY_INSTRUCTION,
            "about": ABOUT_INSTRUCTION,
            "tldr": TLDR_INSTRUCTION,
        }
    return _BUILTIN_PROMPT_DEFAULTS_CACHE


def _get_builtin_alias_defaults() -> dict[str, str]:
    """Return the built-in /tldr alias prompts keyed by alias name.

    Cached after first call. {lang} placeholders are kept verbatim so the
    UI can decide how to render them (defaults dialog shows the raw body).
    """
    global _BUILTIN_ALIAS_DEFAULTS_CACHE
    if _BUILTIN_ALIAS_DEFAULTS_CACHE is None:
        from yoink_insight.services.tldr import _BUILTIN_ALIASES
        _BUILTIN_ALIAS_DEFAULTS_CACHE = dict(_BUILTIN_ALIASES)
    return _BUILTIN_ALIAS_DEFAULTS_CACHE


async def _load_user_prompts(session: AsyncSession, user_id: int) -> dict[str, str]:
    rows = (await session.execute(
        select(InsightUserPrompt).where(InsightUserPrompt.user_id == user_id)
    )).scalars().all()
    return {r.command: r.prompt for r in rows if r.prompt and r.prompt.strip()}


@router.get("/settings/me", response_model=InsightUserSettingsResponse, summary="My AI summary settings")
async def get_my_insight_settings(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightUserSettingsResponse:
    has_gemini_access = await _has_insight_access(session, current_user)
    has_tldr = await _has_feature_access(session, current_user, "tldr")
    has_search = await _has_feature_access(session, current_user, "search")
    config = InsightConfig()
    settings_row = await session.get(InsightUserSettings, current_user.id)
    lang = settings_row.lang if settings_row else config.insight_default_lang
    tldr_model = settings_row.tldr_model if settings_row else None
    github_token = settings_row.github_token if settings_row else None
    use_search = bool(settings_row.use_search) if settings_row else False
    allowed = await _get_tldr_allowed_models_from_db(session, config)
    user_prompts = await _load_user_prompts(session, current_user.id)
    return InsightUserSettingsResponse(
        lang=lang,
        has_gemini_access=has_gemini_access,
        has_tldr_access=has_tldr,
        has_search_access=has_search,
        tldr_model=tldr_model,
        tldr_allowed_models=allowed if has_tldr else [],
        github_token_set=bool(github_token),
        use_search=use_search if has_search else False,
        prompts=user_prompts,
        prompt_defaults=_get_builtin_prompt_defaults(),
        alias_defaults=_get_builtin_alias_defaults(),
    )


@router.patch("/settings/me", response_model=InsightUserSettingsResponse, summary="Update my AI summary settings")
async def update_my_insight_settings(
    body: InsightSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightUserSettingsResponse:
    has_gemini_access = await _has_insight_access(session, current_user)
    has_tldr = await _has_feature_access(session, current_user, "tldr")
    has_search = await _has_feature_access(session, current_user, "search")
    if not has_gemini_access and not has_tldr:
        raise HTTPException(status_code=403, detail="You do not have Insight access.")

    config = InsightConfig()

    # Validate tldr_model against allowed list (owner bypasses)
    tldr_model = body.tldr_model
    if tldr_model is not None and not _is_owner(current_user):
        allowed = await _get_tldr_allowed_models_from_db(session, config)
        if tldr_model not in allowed:
            raise HTTPException(status_code=400, detail=f"Model '{tldr_model}' is not in the allowed list.")

    # use_search requires the 'insight:search' feature.
    if body.use_search is True and not has_search:
        raise HTTPException(status_code=403, detail="You do not have AI Search access.")

    settings_row = await session.get(InsightUserSettings, current_user.id)
    if settings_row is None:
        settings_row = InsightUserSettings(
            user_id=current_user.id,
            lang=body.lang,
            tldr_model=tldr_model,
            github_token=body.github_token,
            use_search=bool(body.use_search) if body.use_search is not None else False,
        )
        session.add(settings_row)
    else:
        settings_row.lang = body.lang
        if tldr_model is not None or body.tldr_model is not None:
            settings_row.tldr_model = tldr_model
        if body.github_token is not None:
            settings_row.github_token = body.github_token or None
        if body.use_search is not None:
            settings_row.use_search = bool(body.use_search)

    # Prompt overrides: only commands matching the user's granted features
    # are accepted; the rest are silently dropped to avoid noisy 4xx on a
    # full settings PATCH that includes inactive command fields.
    if body.prompts is not None:
        allowed_commands: set[str] = set()
        if has_gemini_access:
            allowed_commands.update({"summary", "about"})
        if has_tldr:
            allowed_commands.add("tldr")
        for cmd, prompt in body.prompts.items():
            if cmd not in allowed_commands:
                continue
            existing = await session.get(InsightUserPrompt, (current_user.id, cmd))
            if not prompt or not prompt.strip():
                if existing is not None:
                    await session.delete(existing)
                continue
            if existing is None:
                session.add(InsightUserPrompt(
                    user_id=current_user.id,
                    command=cmd,
                    prompt=prompt.strip(),
                ))
            else:
                existing.prompt = prompt.strip()
                existing.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(settings_row)
    allowed = await _get_tldr_allowed_models_from_db(session, config)
    user_prompts = await _load_user_prompts(session, current_user.id)
    return InsightUserSettingsResponse(
        lang=settings_row.lang,
        has_gemini_access=has_gemini_access,
        has_tldr_access=has_tldr,
        has_search_access=has_search,
        tldr_model=settings_row.tldr_model,
        tldr_allowed_models=allowed if has_tldr else [],
        github_token_set=bool(settings_row.github_token),
        use_search=bool(settings_row.use_search) if has_search else False,
        prompts=user_prompts,
        prompt_defaults=_get_builtin_prompt_defaults(),
        alias_defaults=_get_builtin_alias_defaults(),
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


# --- User TLDR aliases ---

_MAX_ALIASES_PER_USER = 20


_BUILTIN_ALIAS_NAMES = {"max", "nobullshit", "noshit"}


def _row_to_response(row: InsightTldrAlias) -> TldrAliasResponse:
    return TldrAliasResponse(
        id=row.id,
        aliases=row.aliases,
        prompt=row.prompt,
        domains=row.domains,
        target_alias=row.target_alias,
        created_at=row.created_at,
    )


def _validate_alias_keys(raw: str) -> list[str]:
    """Parse, normalise, and validate a comma-separated alias-keyword string."""
    from yoink_insight.services.tldr import parse_aliases
    keys = parse_aliases(raw)
    if not keys:
        raise HTTPException(status_code=400, detail="aliases must not be empty.")
    for k in keys:
        if not k.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(status_code=400, detail=f"'{k}' contains invalid characters.")
        if k in _BUILTIN_ALIAS_NAMES:
            raise HTTPException(status_code=400, detail=f"'{k}' is a built-in alias and cannot be overridden.")
    return keys


def _validate_domains(raw: str | None) -> list[str]:
    """Parse, normalise, and validate a comma-separated domain-glob string.

    Globs accept fnmatch syntax. We lowercase tokens and reject obviously
    malformed entries (whitespace, schemes); empty list is allowed and means
    "no domain binding".
    """
    from yoink_insight.services.tldr import parse_domains
    if not raw or not raw.strip():
        return []
    domains = parse_domains(raw)
    for d in domains:
        if any(c.isspace() for c in d):
            raise HTTPException(status_code=400, detail=f"'{d}' contains whitespace.")
        if "://" in d:
            raise HTTPException(status_code=400, detail=f"'{d}' must not include scheme (use host[/path]).")
    return domains


def _validate_target_alias(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    if key not in _BUILTIN_ALIAS_NAMES:
        raise HTTPException(status_code=400, detail=f"'{key}' is not a known built-in alias.")
    return key


def _collect_existing_keys(rows: list[InsightTldrAlias]) -> set[str]:
    from yoink_insight.services.tldr import parse_aliases
    out: set[str] = set()
    for r in rows:
        if r.aliases:
            out.update(parse_aliases(r.aliases))
    return out


@router.get("/aliases", response_model=list[TldrAliasResponse], summary="List my /tldr aliases")
async def list_my_aliases(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TldrAliasResponse]:
    if not await _has_feature_access(session, current_user, "tldr"):
        raise HTTPException(status_code=403, detail="No TLDR access.")
    rows = (await session.execute(
        select(InsightTldrAlias)
        .where(InsightTldrAlias.user_id == current_user.id)
        .order_by(InsightTldrAlias.created_at)
    )).scalars().all()
    return [_row_to_response(r) for r in rows]


@router.post("/aliases", response_model=TldrAliasResponse, status_code=201, summary="Create /tldr alias")
async def create_alias(
    body: TldrAliasCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TldrAliasResponse:
    if not await _has_feature_access(session, current_user, "tldr"):
        raise HTTPException(status_code=403, detail="No TLDR access.")

    target_alias = _validate_target_alias(body.target_alias)
    domains = _validate_domains(body.domains)
    keys: list[str] = []
    if body.aliases and body.aliases.strip():
        keys = _validate_alias_keys(body.aliases)

    # Shape rule: either keys+prompt, or target_alias, or domains-only-with-target.
    if keys and not (body.prompt and body.prompt.strip()):
        raise HTTPException(status_code=400, detail="prompt is required when aliases are provided.")
    if not keys and not target_alias:
        raise HTTPException(status_code=400, detail="Provide aliases+prompt, or target_alias, or both.")
    if not keys and not domains and target_alias:
        raise HTTPException(status_code=400, detail="target_alias rows must carry at least one domain.")

    existing_rows = (await session.execute(
        select(InsightTldrAlias).where(InsightTldrAlias.user_id == current_user.id)
    )).scalars().all()
    if len(existing_rows) >= _MAX_ALIASES_PER_USER:
        raise HTTPException(status_code=400, detail=f"Maximum {_MAX_ALIASES_PER_USER} aliases per user.")
    conflicts = set(keys) & _collect_existing_keys(list(existing_rows))
    if conflicts:
        raise HTTPException(status_code=409, detail=f"Already exists: {', '.join(sorted(conflicts))}.")

    row = InsightTldrAlias(
        user_id=current_user.id,
        aliases=", ".join(keys) if keys else None,
        prompt=body.prompt.strip() if (keys and body.prompt) else None,
        domains=", ".join(domains) if domains else None,
        target_alias=target_alias,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _row_to_response(row)


@router.patch("/aliases/{alias_id}", response_model=TldrAliasResponse, summary="Update /tldr alias")
async def update_alias(
    alias_id: int,
    body: TldrAliasUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TldrAliasResponse:
    row = await session.get(InsightTldrAlias, alias_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Alias not found.")

    new_target = _validate_target_alias(body.target_alias) if body.target_alias is not None else row.target_alias
    new_domains_list = _validate_domains(body.domains) if body.domains is not None else (
        []
        if row.domains is None
        else _validate_domains(row.domains)
    )
    new_keys: list[str] = []
    if body.aliases is not None:
        if body.aliases.strip():
            new_keys = _validate_alias_keys(body.aliases)
    elif row.aliases:
        from yoink_insight.services.tldr import parse_aliases
        new_keys = parse_aliases(row.aliases)

    new_prompt = body.prompt if body.prompt is not None else row.prompt
    if new_keys and not (new_prompt and new_prompt.strip()):
        raise HTTPException(status_code=400, detail="prompt is required when aliases are provided.")
    if not new_keys and not new_target:
        raise HTTPException(status_code=400, detail="Provide aliases+prompt, or target_alias.")
    if not new_keys and not new_domains_list and new_target:
        raise HTTPException(status_code=400, detail="target_alias rows must carry at least one domain.")

    # Conflict check across OTHER rows (only if keys present).
    if new_keys:
        other_rows = (await session.execute(
            select(InsightTldrAlias).where(
                InsightTldrAlias.user_id == current_user.id,
                InsightTldrAlias.id != alias_id,
            )
        )).scalars().all()
        conflicts = set(new_keys) & _collect_existing_keys(list(other_rows))
        if conflicts:
            raise HTTPException(status_code=409, detail=f"Already used in another alias: {', '.join(sorted(conflicts))}.")

    row.aliases = ", ".join(new_keys) if new_keys else None
    row.prompt = new_prompt.strip() if (new_keys and new_prompt) else None
    row.domains = ", ".join(new_domains_list) if new_domains_list else None
    row.target_alias = new_target
    await session.commit()
    await session.refresh(row)
    return _row_to_response(row)


@router.delete("/aliases/{alias_id}", status_code=204, summary="Delete /tldr alias")
async def delete_alias(
    alias_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    row = await session.get(InsightTldrAlias, alias_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Alias not found.")
    await session.delete(row)
    await session.commit()
