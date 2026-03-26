"""Insight plugin ORM models."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from yoink.core.db.base import Base

# Alias used by plugin model discovery
InsightBase = Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
