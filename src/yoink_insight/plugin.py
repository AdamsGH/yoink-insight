"""InsightPlugin - implements YoinkPlugin protocol."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from yoink.core.plugin import (
    FeatureSpec,
    InlineHandlerSpec,
    JobSpec,
    PluginContext,
    SidebarEntry,
    WebManifest,
    WebPage,
)
from yoink_insight.config import InsightConfig


class InsightPlugin:
    name = "insight"
    version = "0.1.0"

    def __init__(self) -> None:
        self._config = InsightConfig()

    def get_config_class(self) -> type[InsightConfig]:
        return InsightConfig

    def get_models(self) -> list:
        from yoink_insight.storage.models import InsightAccess, InsightSummaryCache, InsightUsageLog, InsightUserSettings
        return [InsightAccess, InsightUserSettings, InsightUsageLog, InsightSummaryCache]

    def get_handlers(self) -> list:
        from yoink_insight.commands import get_handler_specs
        return get_handler_specs()

    def get_inline_handlers(self) -> list[InlineHandlerSpec]:
        return []

    def get_routes(self) -> APIRouter | None:
        from yoink_insight.api.router import router
        return router

    def get_locale_dir(self) -> Path | None:
        return Path(__file__).parent / "i18n" / "locales"

    def get_web_manifest(self) -> WebManifest:
        return WebManifest(pages=[
            WebPage(
                path="/insight/settings",
                sidebar=SidebarEntry(
                    label="AI Settings",
                    icon="Brain",
                    path="/insight/settings",
                    section="main",
                ),
            ),
            WebPage(
                path="/admin/insight-access",
                sidebar=SidebarEntry(
                    label="Insight Access",
                    icon="Key",
                    path="/admin/insight-access",
                    section="admin",
                    min_role="admin",
                ),
            ),
        ])

    def get_commands(self) -> list:
        import yaml
        from yoink.core.plugin import CommandSpec

        locales_dir = Path(__file__).parent / "i18n" / "locales"
        en_data = yaml.safe_load((locales_dir / "en.yml").read_text())

        lang_descriptions: dict[str, dict[str, str]] = {}
        for locale_file in locales_dir.glob("*.yml"):
            lang = locale_file.stem
            if lang == "en":
                continue
            try:
                loc_data = yaml.safe_load(locale_file.read_text())
                for entry in (loc_data.get("commands") or []):
                    cmd = entry.get("command")
                    desc = entry.get("description")
                    if cmd and desc:
                        lang_descriptions.setdefault(cmd, {})[lang] = desc
            except Exception:
                pass

        return [
            CommandSpec(
                command=entry["command"],
                description=entry["description"],
                min_role=entry.get("min_role", "user"),
                scope=entry.get("scope", "default"),
                descriptions=lang_descriptions.get(entry["command"], {}),
                required_feature=entry.get("required_feature"),
            )
            for entry in (en_data.get("commands") or [])
        ]

    def get_help_section(self, role: str, lang: str, granted_features: set[str] | None = None) -> str:
        import yaml
        from yoink.core.plugin import CommandSpec

        _ROLE_RANK = {"user": 0, "moderator": 1, "admin": 2, "owner": 3}
        rank = _ROLE_RANK.get(role, 0)

        locales_dir = Path(__file__).parent / "i18n" / "locales"
        en_data = yaml.safe_load((locales_dir / "en.yml").read_text())
        loc_file = locales_dir / f"{lang}.yml"
        loc_data = yaml.safe_load(loc_file.read_text()) if loc_file.exists() else {}

        def _section(key: str) -> dict:
            return loc_data.get("help_sections", {}).get(key) \
                or en_data.get("help_sections", {}).get(key) \
                or {}

        def _cmd_desc(cmd_name: str, cmd_en_desc: str) -> str:
            for entry in (loc_data.get("commands") or []):
                if entry.get("command") == cmd_name:
                    return entry.get("description") or cmd_en_desc
            return cmd_en_desc

        cmds: list[CommandSpec] = self.get_commands()
        visible = [
            c for c in cmds
            if _ROLE_RANK.get(c.min_role, 0) <= rank
            and (
                c.required_feature is None
                or granted_features is None
                or c.required_feature in granted_features
            )
        ]

        _SECTION_ORDER = [
            ("user",  "insight",       ("default", "private")),
            ("admin", "admin_insight", ("default", "private")),
        ]

        parts: list[str] = []
        for min_role, section_key, scopes in _SECTION_ORDER:
            if _ROLE_RANK.get(min_role, 0) > rank:
                continue
            sec_cmds = [
                c for c in visible
                if c.min_role == min_role and c.scope in scopes
            ]
            if not sec_cmds:
                continue
            sec = _section(section_key)
            title = sec.get("title", section_key.title())
            footer = sec.get("footer", "")
            lines = [f"/{c.command}  - {_cmd_desc(c.command, c.description)}" for c in sec_cmds]
            body = "\n".join(lines)
            if footer:
                body += f"\n\n{footer}"
            is_secondary = min_role != "user"
            if is_secondary:
                parts.append(f"<blockquote expandable><b>{title}</b>\n{body}</blockquote>")
            else:
                parts.append(f"<b>{title}</b>\n{body}")

        return "\n\n".join(parts)

    def get_features(self) -> list[FeatureSpec]:
        return [
            FeatureSpec(
                plugin="insight",
                feature="summary",
                label="AI Summary",
                description="Access to /summary and /about commands (YouTube transcript + Gemini)",
                default_min_role=None,  # explicit grant required; owner always passes
            ),
        ]

    def get_jobs(self) -> list[JobSpec] | None:
        async def _evict_cache(context: object) -> None:
            repo = None
            if hasattr(context, "bot_data"):
                repo = context.bot_data.get("insight_summary_cache")
            if repo is not None:
                evicted = await repo.evict_expired()
                if evicted:
                    import logging
                    logging.getLogger(__name__).debug(
                        "Evicted %d expired insight cache entries", evicted
                    )

        return [
            JobSpec(callback=_evict_cache, interval=3600.0, first=120.0, name="insight_cache_evict"),
        ]

    async def setup(self, ctx: PluginContext) -> None:
        """Populate bot_data with insight-specific services."""
        from yoink_insight.services.access import InsightAccessService
        from yoink_insight.storage.repos import InsightAccessRepo, InsightUsageLogRepo, InsightUserSettingsRepo

        config = self._config
        repo = InsightAccessRepo(ctx.session_factory)
        settings_repo = InsightUserSettingsRepo(ctx.session_factory)
        usage_repo = InsightUsageLogRepo(ctx.session_factory)
        owner_id = ctx.config.owner_id
        access_service = InsightAccessService(repo, owner_id, ctx.session_factory)

        from yoink_insight.storage.repos import InsightSummaryCacheRepo  # noqa: PLC0415
        cache_repo = InsightSummaryCacheRepo(ctx.session_factory)

        ctx.bot_data["insight_config"] = config
        ctx.bot_data["insight_repo"] = repo
        ctx.bot_data["insight_settings_repo"] = settings_repo
        ctx.bot_data["insight_usage_repo"] = usage_repo
        ctx.bot_data["insight_access"] = access_service
        ctx.bot_data["insight_summary_cache"] = cache_repo

        from yoink.core.activity import register_activity_provider  # noqa: PLC0415
        from yoink_insight.activity import insight_activity_provider  # noqa: PLC0415
        register_activity_provider("insight", insight_activity_provider)
