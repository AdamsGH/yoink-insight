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


class InsightAccessGrant(BaseModel):
    lang: str = "en"


class InsightSettingsUpdate(BaseModel):
    lang: str
