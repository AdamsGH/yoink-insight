"""GitHub OAuth device-flow login, per-user.

Mirrors the gateway's src/copilot/auth.py but stores the resulting token
into insight_user_settings.github_token (per yoink user_id) instead of the
gateway-side singleton table. Reuses the VS Code Copilot client_id so we
don't have to register a separate GitHub OAuth App, scope is read:user
which is plenty for the GitHub-API read paths /tldr exercises.

Lifecycle:
  start_device_flow(user_id) -> ask GitHub for device_code, spawn a
    background poll task, return state for the UI (user_code, verification
    URL, expires, poll interval).
  get_device_flow_status(user_id) -> last known state for that user.
  cancel_device_flow(user_id) -> drop in-memory state.

State is in-process only (a singleton per user_id keyed dict); if the
yoink API restarts mid-flow the user simply re-runs the login.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from yoink_insight.storage.repos import InsightUserSettingsRepo

logger = logging.getLogger(__name__)

# VS Code Copilot OAuth App, shared with the gateway. read:user is the
# narrowest scope GitHub accepts here. To raise scope (e.g. public_repo /
# repo) you must register a separate OAuth App and replace this constant.
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_APP_SCOPES = "read:user"

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

_USER_AGENT = "yoink-insight-device-flow/1.0"


@dataclass
class DeviceFlowState:
    """In-memory state for one user's ongoing device-flow login."""

    user_id: int
    device_code: str
    user_code: str
    verification_uri: str
    expires_at: float          # unix seconds
    interval: int              # poll interval, seconds
    status: str = "pending"    # pending | success | expired | error
    error: Optional[str] = None
    username: Optional[str] = None
    started_at: float = field(default_factory=time.time)


_pending: dict[int, DeviceFlowState] = {}
_pending_public_repo: dict[int, DeviceFlowState] = {}
_lock = asyncio.Lock()


async def start_device_flow(user_id: int, session_factory) -> DeviceFlowState:
    """Begin a device-flow login for `user_id`, cancelling any prior flow."""
    async with _lock:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                GITHUB_DEVICE_CODE_URL,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "user-agent": _USER_AGENT,
                },
                json={"client_id": GITHUB_CLIENT_ID, "scope": GITHUB_APP_SCOPES},
            )
            resp.raise_for_status()
            data = resp.json()
        state = DeviceFlowState(
            user_id=user_id,
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data.get("verification_uri", "https://github.com/login/device"),
            expires_at=time.time() + int(data.get("expires_in", 900)),
            interval=max(int(data.get("interval", 5)), 1),
        )
        _pending[user_id] = state
    asyncio.create_task(_poll_until_done(state, session_factory))
    return state


async def get_device_flow_status(user_id: int) -> Optional[DeviceFlowState]:
    return _pending.get(user_id)


async def cancel_device_flow(user_id: int) -> None:
    async with _lock:
        _pending.pop(user_id, None)


async def _poll_until_done(state: DeviceFlowState, session_factory) -> None:
    """Background task: poll GitHub for the access_token, then persist."""
    while True:
        now = time.time()
        if now >= state.expires_at:
            state.status = "expired"
            state.error = "Device code expired before authorisation."
            return
        await asyncio.sleep(state.interval)

        # If the user cancelled or a new flow superseded this one, stop.
        current = _pending.get(state.user_id)
        if current is not state:
            return

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    GITHUB_ACCESS_TOKEN_URL,
                    headers={
                        "accept": "application/json",
                        "content-type": "application/json",
                        "user-agent": _USER_AGENT,
                    },
                    json={
                        "client_id": GITHUB_CLIENT_ID,
                        "device_code": state.device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.exception("github device-flow poll failed for user=%d", state.user_id)
            state.status = "error"
            state.error = repr(exc)
            return

        err = data.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            state.interval = state.interval + 5
            continue
        if err == "expired_token":
            state.status = "expired"
            state.error = "Device code expired before authorisation."
            return
        if err:
            state.status = "error"
            state.error = data.get("error_description") or err
            return

        access_token = data.get("access_token")
        if not access_token:
            state.status = "error"
            state.error = "GitHub returned no access_token and no error."
            return

        # Look up the username so the UI can show 'Signed in as @x'.
        username: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                ur = await client.get(
                    GITHUB_USER_URL,
                    headers={
                        "authorization": f"token {access_token}",
                        "accept": "application/json",
                        "user-agent": _USER_AGENT,
                    },
                )
                if ur.is_success:
                    username = ur.json().get("login")
        except Exception:
            logger.exception("github /user lookup failed; storing token anyway")

        try:
            repo = InsightUserSettingsRepo(session_factory)
            await repo.set_github_token(state.user_id, access_token)
        except Exception as exc:
            logger.exception("failed to persist github token for user=%d", state.user_id)
            state.status = "error"
            state.error = f"persist failed: {exc!r}"
            return

        state.username = username
        state.status = "success"
        return


# ---------------------------------------------------------------------------
# public_repo device flow (separate OAuth App, separate in-memory store)
# ---------------------------------------------------------------------------


async def start_public_repo_flow(
    user_id: int,
    session_factory,
    client_id: str,
) -> DeviceFlowState:
    """Start a device-flow for the public_repo OAuth App.

    Stores resulting token in insight_user_settings.github_token_public_repo.
    """
    async with _lock:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                GITHUB_DEVICE_CODE_URL,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "user-agent": _USER_AGENT,
                },
                json={"client_id": client_id, "scope": "public_repo"},
            )
            resp.raise_for_status()
            data = resp.json()
        state = DeviceFlowState(
            user_id=user_id,
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data.get("verification_uri", "https://github.com/login/device"),
            expires_at=time.time() + int(data.get("expires_in", 900)),
            interval=max(int(data.get("interval", 5)), 1),
        )
        _pending_public_repo[user_id] = state
    asyncio.create_task(_poll_public_repo(state, session_factory, client_id))
    return state


async def get_public_repo_flow_status(user_id: int) -> Optional[DeviceFlowState]:
    return _pending_public_repo.get(user_id)


async def cancel_public_repo_flow(user_id: int) -> None:
    async with _lock:
        _pending_public_repo.pop(user_id, None)


async def _poll_public_repo(
    state: DeviceFlowState, session_factory, client_id: str
) -> None:
    while True:
        if time.time() >= state.expires_at:
            state.status = "expired"
            state.error = "Device code expired before authorisation."
            return
        await asyncio.sleep(state.interval)

        current = _pending_public_repo.get(state.user_id)
        if current is not state:
            return

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    GITHUB_ACCESS_TOKEN_URL,
                    headers={
                        "accept": "application/json",
                        "content-type": "application/json",
                        "user-agent": _USER_AGENT,
                    },
                    json={
                        "client_id": client_id,
                        "device_code": state.device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.exception("public_repo poll failed for user=%d", state.user_id)
            state.status = "error"
            state.error = repr(exc)
            return

        err = data.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            state.interval += 5
            continue
        if err == "expired_token":
            state.status = "expired"
            state.error = "Device code expired before authorisation."
            return
        if err:
            state.status = "error"
            state.error = data.get("error_description") or err
            return

        access_token = data.get("access_token")
        if not access_token:
            state.status = "error"
            state.error = "GitHub returned no access_token and no error."
            return

        username: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                ur = await client.get(
                    GITHUB_USER_URL,
                    headers={
                        "authorization": f"token {access_token}",
                        "accept": "application/json",
                        "user-agent": _USER_AGENT,
                    },
                )
                if ur.is_success:
                    username = ur.json().get("login")
        except Exception:
            logger.exception("github /user lookup failed for public_repo flow")

        try:
            repo = InsightUserSettingsRepo(session_factory)
            await repo.set_github_token_public_repo(state.user_id, access_token)
        except Exception as exc:
            logger.exception("failed to persist public_repo token for user=%d", state.user_id)
            state.status = "error"
            state.error = f"persist failed: {exc!r}"
            return

        state.username = username
        state.status = "success"
