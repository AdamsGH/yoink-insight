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
    tldr_model: str | None = None
    github_token: str | None = None


class InsightUserSettingsResponse(BaseModel):
    lang: str
    has_gemini_access: bool
    has_tldr_access: bool = False
    tldr_model: str | None = None
    tldr_allowed_models: list[str] = []
    github_token_set: bool = False


class TldrConfigResponse(BaseModel):
    allowed_models: list[str]
    default_model: str
    gateway_base_url: str
    gateway_api_key: str


class TldrConfigUpdate(BaseModel):
    allowed_models: list[str]
    default_model: str
    gateway_base_url: str
    gateway_api_key: str


class UserLookupResult(BaseModel):
    id: int
    username: str | None
    first_name: str | None


class TldrAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    aliases: str
    prompt: str
    created_at: datetime


class TldrAliasCreate(BaseModel):
    aliases: str
    prompt: str


class TldrAliasUpdate(BaseModel):
    aliases: str
    prompt: str
