"""Insight plugin repositories."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case as sa_case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from yoink.core.db.models import User
from yoink_insight.storage.models import (
    InsightAccess,
    InsightSummaryCache,
    InsightUsageLog,
    InsightUserByok,
    InsightUserPrompt,
    InsightUserSettings,
)

_CACHE_TTL_HOURS = 24


class InsightSummaryCacheRepo:
    """Read/write cached LLM results by (content_key, lang, command).

    content_key is a YouTube video ID for /summary and /about, or a
    normalized URL for /tldr on web pages.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def get(self, content_key: str, lang: str, command: str) -> str | None:
        """Return cached result if it exists and has not expired."""
        now = datetime.now(timezone.utc)
        async with self._sf() as s:
            result = await s.execute(
                select(InsightSummaryCache.result)
                .where(
                    InsightSummaryCache.content_key == content_key,
                    InsightSummaryCache.lang == lang,
                    InsightSummaryCache.command == command,
                    InsightSummaryCache.expires_at > now,
                )
            )
            row = result.scalar_one_or_none()
            return row

    async def set(self, content_key: str, lang: str, command: str, result: str) -> None:
        """Upsert a cached result with a fresh TTL."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=_CACHE_TTL_HOURS)
        async with self._sf() as s:
            stmt = (
                pg_insert(InsightSummaryCache)
                .values(
                    content_key=content_key,
                    lang=lang,
                    command=command,
                    result=result,
                    created_at=now,
                    expires_at=expires_at,
                )
                .on_conflict_do_update(
                    constraint="uq_insight_cache_key",
                    set_={"result": result, "created_at": now, "expires_at": expires_at},
                )
            )
            await s.execute(stmt)
            await s.commit()

    async def evict_expired(self) -> int:
        """Delete all expired cache entries. Called by cleanup job."""
        now = datetime.now(timezone.utc)
        async with self._sf() as s:
            result = await s.execute(
                delete(InsightSummaryCache).where(InsightSummaryCache.expires_at <= now)
            )
            await s.commit()
            return result.rowcount


class InsightUserSettingsRepo:
    """CRUD for insight_user_settings (language preferences)."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def get_lang(self, user_id: int, default: str = "en") -> str:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            return row.lang if row is not None else default

    async def get_tldr_model(self, user_id: int) -> str | None:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            return row.tldr_model if row is not None else None

    async def set_tldr_model(self, user_id: int, model: str | None) -> InsightUserSettings:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            if row is None:
                user = await s.get(User, user_id)
                if user is None:
                    user = User(id=user_id)
                    s.add(user)
                    await s.flush()
                row = InsightUserSettings(user_id=user_id, tldr_model=model)
                s.add(row)
            else:
                row.tldr_model = model
            await s.commit()
            await s.refresh(row)
            return row

    async def get_github_token(self, user_id: int) -> str | None:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            return row.github_token if row is not None else None

    async def get_use_search(self, user_id: int) -> bool:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            return bool(row.use_search) if row is not None else False

    async def set_use_search(self, user_id: int, value: bool) -> InsightUserSettings:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            if row is None:
                user = await s.get(User, user_id)
                if user is None:
                    user = User(id=user_id)
                    s.add(user)
                    await s.flush()
                row = InsightUserSettings(user_id=user_id, use_search=value)
                s.add(row)
            else:
                row.use_search = value
            await s.commit()
            await s.refresh(row)
            return row

    async def set_github_token(self, user_id: int, token: str | None) -> InsightUserSettings:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            if row is None:
                user = await s.get(User, user_id)
                if user is None:
                    user = User(id=user_id)
                    s.add(user)
                    await s.flush()
                row = InsightUserSettings(user_id=user_id, github_token=token)
                s.add(row)
            else:
                row.github_token = token
            await s.commit()
            await s.refresh(row)
            return row

    async def get_github_token_public_repo(self, user_id: int) -> str | None:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            return row.github_token_public_repo if row is not None else None

    async def set_github_token_public_repo(self, user_id: int, token: str | None) -> InsightUserSettings:
        async with self._sf() as s:
            row = await s.get(InsightUserSettings, user_id)
            if row is None:
                user = await s.get(User, user_id)
                if user is None:
                    user = User(id=user_id)
                    s.add(user)
                    await s.flush()
                row = InsightUserSettings(user_id=user_id, github_token_public_repo=token)
                s.add(row)
            else:
                row.github_token_public_repo = token
            await s.commit()
            await s.refresh(row)
            return row

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


class InsightUserByokRepo:
    """CRUD for insight_user_byok (per-user Bring-Your-Own-Key configs)."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def get(self, user_id: int) -> InsightUserByok | None:
        async with self._sf() as s:
            return await s.get(InsightUserByok, user_id)

    async def upsert(
        self,
        user_id: int,
        *,
        provider: str,
        base_url: str | None,
        api_key: str,
        model: str,
        models_json: str | None = None,
        tested_at: datetime | None = None,
        test_error: str | None = None,
    ) -> InsightUserByok:
        async with self._sf() as s:
            user = await s.get(User, user_id)
            if user is None:
                user = User(id=user_id)
                s.add(user)
                await s.flush()
            now = datetime.now(timezone.utc)
            row = await s.get(InsightUserByok, user_id)
            if row is None:
                row = InsightUserByok(
                    user_id=user_id,
                    provider=provider,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    models_json=models_json,
                    models_fetched_at=now if models_json else None,
                    tested_at=tested_at,
                    test_error=test_error,
                    created_at=now,
                    updated_at=now,
                )
                s.add(row)
            else:
                row.provider = provider
                row.base_url = base_url
                row.api_key = api_key
                row.model = model
                if models_json is not None:
                    row.models_json = models_json
                    row.models_fetched_at = now
                row.tested_at = tested_at if tested_at is not None else row.tested_at
                row.test_error = test_error
                row.updated_at = now
            await s.commit()
            await s.refresh(row)
            return row

    async def update_models(
        self,
        user_id: int,
        models_json: str,
        tested_at: datetime | None,
        test_error: str | None,
    ) -> InsightUserByok | None:
        async with self._sf() as s:
            row = await s.get(InsightUserByok, user_id)
            if row is None:
                return None
            now = datetime.now(timezone.utc)
            row.models_json = models_json
            row.models_fetched_at = now
            row.tested_at = tested_at
            row.test_error = test_error
            row.updated_at = now
            await s.commit()
            await s.refresh(row)
            return row

    async def delete(self, user_id: int) -> bool:
        async with self._sf() as s:
            result = await s.execute(
                delete(InsightUserByok).where(InsightUserByok.user_id == user_id)
            )
            await s.commit()
            return result.rowcount > 0

    async def is_ready(self, user_id: int) -> bool:
        """True if the user has a saved BYOK config that passed its last probe.

        "Ready" = row exists, was tested at least once, and last probe did not
        record an error. The global `insight_byok_enabled` toggle is checked
        separately by the caller (it lives in bot_settings, not here).
        """
        async with self._sf() as s:
            row = await s.execute(
                select(InsightUserByok.user_id).where(
                    InsightUserByok.user_id == user_id,
                    InsightUserByok.tested_at.is_not(None),
                    InsightUserByok.test_error.is_(None),
                )
            )
            return row.scalar_one_or_none() is not None

    async def list_user_ids(self) -> list[int]:
        """Every user_id with a stored BYOK row (regardless of probe state)."""
        async with self._sf() as s:
            rows = await s.execute(select(InsightUserByok.user_id))
            return [r[0] for r in rows.all()]


class InsightUserPromptRepo:
    """CRUD for per-user prompt overrides keyed by (user_id, command)."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def get(self, user_id: int, command: str) -> str | None:
        async with self._sf() as s:
            row = await s.get(InsightUserPrompt, (user_id, command))
            if row is None or not row.prompt or not row.prompt.strip():
                return None
            return row.prompt

    async def get_all(self, user_id: int) -> dict[str, str]:
        async with self._sf() as s:
            rows = (await s.execute(
                select(InsightUserPrompt).where(InsightUserPrompt.user_id == user_id)
            )).scalars().all()
            return {r.command: r.prompt for r in rows if r.prompt and r.prompt.strip()}

    async def set(self, user_id: int, command: str, prompt: str | None) -> None:
        """Upsert or delete a prompt override. Empty / None prompt removes the row."""
        async with self._sf() as s:
            row = await s.get(InsightUserPrompt, (user_id, command))
            if not prompt or not prompt.strip():
                if row is not None:
                    await s.delete(row)
                    await s.commit()
                return
            user = await s.get(User, user_id)
            if user is None:
                user = User(id=user_id)
                s.add(user)
                await s.flush()
            if row is None:
                row = InsightUserPrompt(user_id=user_id, command=command, prompt=prompt.strip())
                s.add(row)
            else:
                row.prompt = prompt.strip()
                row.updated_at = datetime.now(timezone.utc)
            await s.commit()


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
        alias_key: str | None = None,
        content_chars: int | None = None,
        video_seconds: int | None = None,
        route: str = "gateway",
    ) -> None:
        async with self._sf() as s:
            s.add(InsightUsageLog(
                user_id=user_id,
                command=command,
                video_id=video_id,
                lang=lang,
                status=status,
                error_code=error_code,
                alias_key=alias_key,
                content_chars=content_chars,
                video_seconds=video_seconds,
                route=route,
            ))
            await s.commit()

    async def count_today(self, user_id: int) -> int:
        """Count all successful LLM calls for this user since UTC midnight (all commands).

        'cached' rows are not counted - only status='ok'.
        """
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._sf() as s:
            result = await s.execute(
                select(func.count()).select_from(InsightUsageLog).where(
                    InsightUsageLog.user_id == user_id,
                    InsightUsageLog.status == "ok",
                    InsightUsageLog.created_at >= today_start,
                )
            )
            return result.scalar() or 0

    async def count_today_command(self, user_id: int, command: str) -> int:
        """Count successful calls for a specific command today (status='ok' only)."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._sf() as s:
            result = await s.execute(
                select(func.count()).select_from(InsightUsageLog).where(
                    InsightUsageLog.user_id == user_id,
                    InsightUsageLog.command == command,
                    InsightUsageLog.status == "ok",
                    InsightUsageLog.created_at >= today_start,
                )
            )
            return result.scalar() or 0

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

    # ------------------------------------------------------------------
    # TLDR-specific stats
    # ------------------------------------------------------------------
    #
    # Time-saved formulas (see api/router.get_my_insight_stats):
    #   YouTube row with video_seconds NOT NULL  -> seconds / 60
    #   YouTube row with video_seconds NULL      -> content_chars-based reading
    #                                              estimate (transcript words)
    #   Web row (video_seconds always NULL)      -> content_chars / 1000 minutes
    #                                              (~200 wpm * ~5 chars per word)
    async def tldr_stats_for_user(self, user_id: int) -> dict:
        """Aggregate TLDR-specific stats for a single user.

        Rows where command='tldr' OR command LIKE 'tldr:%' are considered.
        Only status IN ('ok', 'cached') is counted (errors don't "save time").
        """
        from datetime import timedelta
        from sqlalchemy import Date, cast, or_

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        thirty_days_ago = now - timedelta(days=30)

        tldr_filter = or_(
            InsightUsageLog.command == "tldr",
            InsightUsageLog.command.like("tldr:%"),
        )
        ok_status = InsightUsageLog.status.in_(("ok", "cached"))

        async with self._sf() as s:
            base = select(func.count()).select_from(InsightUsageLog).where(
                InsightUsageLog.user_id == user_id,
                tldr_filter,
                ok_status,
            )
            total = (await s.execute(base)).scalar() or 0
            this_week = (await s.execute(
                base.where(InsightUsageLog.created_at >= week_start)
            )).scalar() or 0
            today = (await s.execute(
                base.where(InsightUsageLog.created_at >= today_start)
            )).scalar() or 0

            # By alias breakdown (alias_key NULL -> bucket "_none")
            alias_rows = (await s.execute(
                select(InsightUsageLog.alias_key, func.count())
                .where(
                    InsightUsageLog.user_id == user_id,
                    tldr_filter,
                    ok_status,
                )
                .group_by(InsightUsageLog.alias_key)
            )).all()
            by_alias = [
                {"alias": row[0] or "_none", "count": row[1]}
                for row in alias_rows
            ]
            by_alias.sort(key=lambda r: r["count"], reverse=True)

            # By kind: youtube (video_seconds NOT NULL) vs web
            yt_count = (await s.execute(
                base.where(InsightUsageLog.video_seconds.is_not(None))
            )).scalar() or 0
            web_count = total - yt_count

            # Aggregate seconds + chars buckets
            sums = (await s.execute(
                select(
                    func.coalesce(func.sum(InsightUsageLog.video_seconds), 0),
                    func.coalesce(
                        func.sum(
                            sa_case((InsightUsageLog.video_seconds.is_(None), InsightUsageLog.content_chars), else_=0)
                        ),
                        0,
                    ),
                ).where(
                    InsightUsageLog.user_id == user_id,
                    tldr_filter,
                    ok_status,
                )
            )).one()
            total_video_seconds = int(sums[0] or 0)
            total_web_chars = int(sums[1] or 0)

            # Daily history (last 30 days) - count + summed metrics
            day_rows = (await s.execute(
                select(
                    cast(InsightUsageLog.created_at, Date).label("date"),
                    func.count().label("count"),
                    func.coalesce(func.sum(InsightUsageLog.video_seconds), 0).label("video_seconds"),
                    func.coalesce(
                        func.sum(
                            sa_case((InsightUsageLog.video_seconds.is_(None), InsightUsageLog.content_chars), else_=0)
                        ),
                        0,
                    ).label("web_chars"),
                )
                .where(
                    InsightUsageLog.user_id == user_id,
                    tldr_filter,
                    ok_status,
                    InsightUsageLog.created_at >= thirty_days_ago,
                )
                .group_by("date")
                .order_by("date")
            )).all()
            by_day = [
                {
                    "date": str(row[0]),
                    "count": row[1],
                    "video_seconds": int(row[2] or 0),
                    "web_chars": int(row[3] or 0),
                }
                for row in day_rows
            ]

        return {
            "total": total,
            "this_week": this_week,
            "today": today,
            "by_alias": by_alias,
            "by_kind": {"youtube": yt_count, "web": web_count},
            "by_day": by_day,
            "total_video_seconds": total_video_seconds,
            "total_web_chars": total_web_chars,
        }
