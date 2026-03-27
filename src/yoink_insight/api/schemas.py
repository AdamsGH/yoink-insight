"""Insight plugin API schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InsightAccessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    lang: str
    granted_by: int
    granted_at: datetime

    # Denormalized from users table - populated by API, not stored in insight_access
    username: str | None = None
    first_name: str | None = None
    granted_by_username: str | None = None


class InsightAccessGrant(BaseModel):
    lang: str = "en"


class InsightSettingsUpdate(BaseModel):
    lang: str


class InsightUserSettingsResponse(BaseModel):
    lang: str
    has_access: bool


class UserLookupResult(BaseModel):
    id: int
    username: str | None
    first_name: str | None
