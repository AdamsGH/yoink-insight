from __future__ import annotations

import httpx
import pytest
from yoink_insight.services import byok


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, *, responses: list[_Response], **kwargs: object) -> None:
        self.responses = responses
        self.kwargs = kwargs
        self.requests: list[tuple[str, dict]] = []

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, **kwargs: dict) -> _Response:
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_openrouter_probe_authenticates_then_loads_public_models_via_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(responses=[
        _Response(200, {"data": {"label": "test"}}),
        _Response(200, {"data": [{"id": "openai/gpt-test"}]}),
    ])
    client_options = []

    def client_factory(**kwargs):
        client_options.append(kwargs)
        return client

    monkeypatch.setattr(byok.httpx, "AsyncClient", client_factory)

    result = await byok.probe(
        "openrouter", None, "unit-test-key", proxy_url="http://proxy.invalid:8080"
    )

    assert result.ok
    assert [model.id for model in result.models] == ["openai/gpt-test"]
    assert len(client_options) == 2
    assert all(options["proxy"] == "http://proxy.invalid:8080" for options in client_options)
    assert [url.rsplit("/", 1)[-1] for url, _ in client.requests] == ["key", "models"]
    assert client.requests[0][1]["headers"]["Authorization"] == "Bearer unit-test-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(401, "invalid_api_key"), (403, "provider_forbidden"), (429, "provider_rate_limited"), (503, "provider_unavailable")],
)
async def test_openrouter_probe_classifies_authenticated_endpoint_errors(
    monkeypatch: pytest.MonkeyPatch, status_code: int, expected: str
) -> None:
    client = _Client(responses=[_Response(status_code)])
    monkeypatch.setattr(byok.httpx, "AsyncClient", lambda **kwargs: client)

    result = await byok.probe("openrouter", None, "unit-test-key")

    assert not result.ok
    assert result.error == expected
    assert len(client.requests) == 1
    assert client.requests[0][0].endswith("/key")


@pytest.mark.asyncio
async def test_openrouter_probe_reports_network_failure_without_catalogue_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient(_Client):
        async def get(self, url: str, **kwargs: dict) -> _Response:
            raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(
        byok.httpx,
        "AsyncClient",
        lambda **kwargs: FailingClient(responses=[], **kwargs),
    )

    result = await byok.probe("openrouter", None, "unit-test-key")

    assert not result.ok
    assert result.error == "network_error"
    assert result.models == []

@pytest.mark.asyncio
async def test_all_byok_routes_pass_openrouter_proxy_and_failed_save_stays_unready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from yoink_insight.api import router
    from yoink_insight.api.schemas import ByokConfigUpdate, ByokTestRequest
    from yoink_insight.storage.models import InsightUserByok

    from yoink.core.db.models import UserRole

    class Session:
        def __init__(self, row: object | None = None) -> None:
            self.row = row
            self.added: object | None = None

        async def get(self, model: object, key: object) -> object | None:
            if model is InsightUserByok:
                return self.row
            return None

        def add(self, row: object) -> None:
            self.added = row
            self.row = row

        async def commit(self) -> None:
            return None

        async def refresh(self, row: object) -> None:
            return None

    monkeypatch.setattr(router, "_get_byok_enabled", lambda session: _enabled())
    monkeypatch.setattr(router, "_refresh_user_bot_commands", lambda *args: _noop())
    monkeypatch.setattr(
        "yoink_insight.config.InsightConfig",
        lambda: SimpleNamespace(proxy_url="http://proxy.invalid:8080"),
    )
    probed: list[str | None] = []

    async def fake_probe(
        provider: str,
        base_url: str | None,
        api_key: str,
        *,
        proxy_url: str | None = None,
    ):
        probed.append(proxy_url)
        if api_key == "bad-key":
            return byok.ProbeResult(ok=False, error="provider_forbidden")
        return byok.ProbeResult(ok=True, models=[byok.ModelInfo("openai/gpt-test", False)])

    async def _enabled() -> bool:
        return True

    async def _noop() -> None:
        return None

    monkeypatch.setattr(byok, "probe", fake_probe)
    user = SimpleNamespace(id=77, role=UserRole.user)

    test_response = await router.test_my_byok(
        ByokTestRequest(provider="openrouter", api_key="good-key"),
        session=Session(),
        current_user=user,
    )
    assert test_response.ok

    save_session = Session()
    saved = await router.put_my_byok(
        ByokConfigUpdate(provider="openrouter", api_key="bad-key", model="openai/gpt-test"),
        request=SimpleNamespace(),
        session=save_session,
        current_user=user,
    )
    assert saved.test_error == "provider_forbidden"
    assert save_session.added is not None
    assert save_session.added.tested_at is None

    row = SimpleNamespace(
        user_id=77,
        provider="openrouter",
        base_url=None,
        api_key="good-key",
        model="openai/gpt-test",
        models_json=None,
        models_fetched_at=None,
        tested_at=None,
        test_error="provider_forbidden",
        updated_at=None,
    )
    refresh_response = await router.refresh_my_byok_models(
        request=SimpleNamespace(),
        session=Session(row),
        current_user=user,
    )
    assert refresh_response.test_error is None
    assert row.tested_at is not None
    assert probed == ["http://proxy.invalid:8080"] * 3


@pytest.mark.parametrize("language", ["en", "ru"])
def test_stream_auth_error_codes_have_loadable_translations(language):
    from importlib.resources import files

    import yaml

    locale = files("yoink_insight").joinpath("i18n", "locales", f"{language}.yml")
    messages = yaml.safe_load(locale.read_text(encoding="utf-8"))
    for status in (401, 403):
        code = byok._classify_provider_status(status)
        assert messages["tldr"]["error"][code]
