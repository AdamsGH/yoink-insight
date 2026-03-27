"""Insight plugin ORM models."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from yoink.core.db.base import Base

# Alias used by plugin model discovery
InsightBase = Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InsightUserSettings(Base):
    """Per-user settings for the Insight plugin.

    Stores preferences (e.g. summary language) separately from access grants.
    Access is controlled by user_permissions(plugin='insight', feature='summary').
    """
    __tablename__ = "insight_user_settings"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    lang: Mapped[str] = mapped_column(String(8), default="en", nullable=False)


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
    command: Mapped[str] = mapped_column(String(16), nullable=False)  # "summary" | "about"
    video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # "ok" | "error"
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
