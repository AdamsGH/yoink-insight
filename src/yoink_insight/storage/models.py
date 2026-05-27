"""Insight plugin ORM models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from yoink.core.db.base import Base, _now


class InsightUserSettings(Base):
    """Per-user settings for the Insight plugin.

    Stores preferences (e.g. summary language, tldr model) separately from access grants.
    Access is controlled by user_permissions(plugin='insight', feature='...').
    """
    __tablename__ = "insight_user_settings"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    lang: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    tldr_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    github_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
    use_search: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class InsightUserPrompt(Base):
    """Per-user prompt override for a specific command.

    command is one of 'summary' | 'about' | 'tldr' (the default no-alias path).
    The presence of a row means "use this prompt instead of the built-in one";
    a missing row falls back to the hard-coded default. NULL/empty prompt is
    treated the same as a missing row by the CRUD layer.
    """
    __tablename__ = "insight_user_prompts"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    command: Mapped[str] = mapped_column(String(16), primary_key=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class InsightAccess(Base):
    """Per-user allowlist entry for the Insight plugin.

    Only users present in this table (or the bot owner) may use /about and /summary.
    The lang column stores the preferred response language for this user.
    """
    __tablename__ = "insight_access"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    lang: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    granted_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class InsightSummaryCache(Base):
    """Cached LLM results keyed by (content_key, lang, command).

    content_key is a YouTube video ID for /summary and /about, or a full URL
    for /tldr on web pages. TTL is 24 hours.
    """
    __tablename__ = "insight_summary_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_key: Mapped[str] = mapped_column(String(512), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    command: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InsightTldrAlias(Base):
    """User-defined /tldr aliases and domain bindings.

    Three row shapes are valid (CHECK constraint enforces at least one):
      1. Custom alias:           aliases='...', prompt='...', domains=NULL|csv, target_alias=NULL
      2. Built-in domain bind:   target_alias='nobullshit', domains='csv', aliases=NULL, prompt=NULL
      3. Custom + domains:       any combination, as long as a resolvable
                                 prompt source exists (custom prompt or built-in target).
    """
    __tablename__ = "insight_tldr_aliases"
    __table_args__ = (
        Index("idx_insight_tldr_alias_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    aliases: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    domains: Mapped[str | None] = mapped_column(String(512), nullable=True)
    target_alias: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class InsightUserByok(Base):
    """Per-user Bring-Your-Own-Key configuration for /tldr.

    Lets users without the insight:tldr grant call /tldr against their own
    OpenAI/Anthropic/Gemini/OpenRouter/Perplexity (or custom-compat) endpoint.
    The admin tumbler bot_settings.insight_byok_enabled gates the whole
    feature.

    provider is one of: openai, anthropic, gemini, openrouter, perplexity,
    custom_openai, custom_anthropic. base_url is required only for custom_*.
    models_json is the cached provider model catalogue (list[dict] with
    {id, supports_websearch}), refreshed on demand. tested_at/test_error
    record the last connectivity probe.
    """
    __tablename__ = "insight_user_byok"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    models_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    models_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    test_error: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class InsightUsageLog(Base):
    """Tracks every /summary and /about invocation."""
    __tablename__ = "insight_usage_log"
    __table_args__ = (
        Index("idx_insight_usage_user_date", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    command: Mapped[str] = mapped_column(String(16), nullable=False)  # "summary" | "about" | "tldr" | "tldr:<alias>"
    video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # "ok" | "error"
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    # TLDR metrics (NULL for non-tldr rows and legacy entries)
    content_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alias_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Path the request took: 'gateway' (default; goes through llmgw) or
    # 'byok' (user-owned provider, gateway bypassed). Required for split
    # cost / usage graphs - the gateway sees zero traffic on the byok path.
    route: Mapped[str] = mapped_column(String(16), nullable=False, default="gateway")
