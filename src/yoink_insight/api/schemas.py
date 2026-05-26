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
    use_search: bool | None = None
    prompts: dict[str, str | None] | None = None


class InsightUserSettingsResponse(BaseModel):
    lang: str
    has_gemini_access: bool
    has_tldr_access: bool = False
    has_search_access: bool = False
    tldr_model: str | None = None
    tldr_allowed_models: list[str] = []
    github_token_set: bool = False
    use_search: bool = False
    prompts: dict[str, str] = {}
    prompt_defaults: dict[str, str] = {}
    alias_defaults: dict[str, str] = {}


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
    aliases: str | None = None
    prompt: str | None = None
    domains: str | None = None
    target_alias: str | None = None
    created_at: datetime


class TldrAliasCreate(BaseModel):
    aliases: str | None = None
    prompt: str | None = None
    domains: str | None = None
    target_alias: str | None = None


class TldrAliasUpdate(BaseModel):
    aliases: str | None = None
    prompt: str | None = None
    domains: str | None = None
    target_alias: str | None = None


class ByokModelInfo(BaseModel):
    id: str
    supports_websearch: bool = False


class ByokProviderInfo(BaseModel):
    id: str
    label: str
    default_base_url: str | None = None
    requires_base_url: bool = False
    api_shape: str = "openai"
    all_websearch: bool = False


class ByokConfigResponse(BaseModel):
    """User-facing view of insight_user_byok row.

    api_key_set is True when the row exists. api_key_masked is the
    last 4 chars prefixed by '...' (or None if the key is shorter than 4).
    The raw key is never returned.
    """
    enabled: bool                              # global admin tumbler
    has_config: bool                           # this user has a saved row
    api_key_set: bool = False
    api_key_masked: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    models: list[ByokModelInfo] = []
    models_fetched_at: datetime | None = None
    tested_at: datetime | None = None
    test_error: str | None = None
    providers: list[ByokProviderInfo] = []


class ByokConfigUpdate(BaseModel):
    provider: str
    base_url: str | None = None
    api_key: str | None = None                 # None / empty -> keep existing
    model: str


class ByokTestRequest(BaseModel):
    provider: str
    base_url: str | None = None
    api_key: str | None = None                 # None -> use stored key


class ByokTestResponse(BaseModel):
    ok: bool
    error: str | None = None
    models: list[ByokModelInfo] = []


class ByokAdminConfig(BaseModel):
    enabled: bool
