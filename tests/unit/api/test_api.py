from __future__ import annotations

from collections.abc import AsyncIterator

import fakeredis
import httpx
import pytest
from fastapi import FastAPI

from aqta.api import Container, build_in_memory_container, create_app
from aqta.core.clock import FrozenClock
from aqta.core.errors import ConfigError
from aqta.core.settings import Settings
from conftest import TEST_API_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_API_TOKEN}"}


@pytest.fixture
def container(settings: Settings, clock: FrozenClock) -> Container:
    return build_in_memory_container(settings, clock)


@pytest.fixture
def app(container: Container) -> FastAPI:
    return create_app(container=container)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "mode": "paper"}
    assert r.headers["x-request-id"].startswith("req_")


async def test_request_id_is_echoed_when_valid(client: httpx.AsyncClient) -> None:
    r = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    r = await client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"].startswith("req_")


async def test_ready_reports_dependencies(client: httpx.AsyncClient) -> None:
    r = await client.get("/ready")
    assert r.status_code == 503
    assert r.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable", "redis": "unavailable"},
    }


async def test_ready_green(
    settings: Settings, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    c = build_in_memory_container(settings, clock, redis=redis)

    async def db_ok() -> bool:
        return True

    monkeypatch.setattr(c, "_db_ok", db_ok)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container=c)), base_url="http://t"
    ) as client:
        r = await client.get("/ready")
    assert r.status_code == 200 and r.json()["checks"] == {"database": "ok", "redis": "ok"}
    await c.close()


async def test_ready_handles_probe_errors(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom() -> bool:
        raise ConnectionRefusedError

    monkeypatch.setattr(container, "_db_ok", boom)
    assert (await container.check_ready())["database"] == "error: ConnectionRefusedError"


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"}]
)
async def test_v1_requires_token(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    r = await client.get("/api/v1/mode", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert r.headers["www-authenticate"] == "Bearer"


async def test_mode(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/mode", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {
        "trading_mode": "paper",
        "live_trading_enabled": False,
        "algo_tag": "AQTA-UNREGISTERED",
    }


async def test_kill_switch_trigger_and_release(
    client: httpx.AsyncClient, container: Container
) -> None:
    r = await client.get("/api/v1/kill-switch", headers=AUTH)
    assert r.json()["active"] is False
    r = await client.post(
        "/api/v1/kill-switch", headers=AUTH, json={"action": "trigger", "reason": "manual drill"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True and body["actor"] == "kashyap"
    assert body["updated_at_ist"].endswith("IST") and body["cancelled_orders"] == 0
    assert (await client.get("/api/v1/kill-switch", headers=AUTH)).json()["active"] is True
    assert await container.kill_switch.is_active()

    r = await client.post(
        "/api/v1/kill-switch", headers=AUTH, json={"action": "release", "reason": "drill over"}
    )
    assert r.json()["active"] is False


async def test_kill_switch_validation_error_shape(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/kill-switch", headers=AUTH, json={"reason": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["request_id"].startswith("req_")


async def test_proposals_stub(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/proposals", headers=AUTH)
    assert r.status_code == 200 and r.json() == []


async def test_mfa_hook_fails_closed(settings: Settings, clock: FrozenClock) -> None:
    c = build_in_memory_container(settings.model_copy(update={"mfa_required": True}), clock)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container=c)), base_url="http://t"
    ) as client:
        r = await client.get("/api/v1/mode", headers=AUTH)
    assert r.status_code == 401 and "MFA" in r.json()["error"]["message"]


async def test_no_configured_token_refuses_everything(
    settings: Settings, clock: FrozenClock
) -> None:
    c = build_in_memory_container(settings.model_copy(update={"api_token": None}), clock)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(container=c)), base_url="http://t"
    ) as client:
        r = await client.get("/api/v1/mode", headers=AUTH)
    assert r.status_code == 401 and "not configured" in r.json()["error"]["message"]


async def test_cors_locked_down(client: httpx.AsyncClient) -> None:
    r = await client.options(
        "/api/v1/mode",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in r.headers


async def test_unhandled_errors_do_not_leak(app: FastAPI) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.get("/boom")
    assert r.status_code == 500
    assert r.json()["error"] == {"code": "internal_error", "message": "internal server error"}
    assert "secret" not in r.text


def test_in_memory_container_refused_in_prod(settings: Settings) -> None:
    prod = settings.model_copy(update={"app_env": "prod"})
    with pytest.raises(ConfigError):
        build_in_memory_container(prod)


def test_container_requires_approval_secret(settings: Settings) -> None:
    from pydantic import SecretStr

    with pytest.raises(ConfigError, match="APPROVAL_SECRET"):
        build_in_memory_container(settings.model_copy(update={"approval_secret": SecretStr("")}))


@pytest.mark.parametrize(
    ("env", "enabled", "expected"),
    [
        ("test", False, 200),
        ("prod", False, 404),
        ("prod", True, 200),
    ],
)
async def test_docs_visibility(
    settings: Settings, clock: FrozenClock, env: str, enabled: bool, expected: int
) -> None:
    s = settings.model_copy(update={"app_env": env, "docs_enabled": enabled})
    c = build_in_memory_container(settings, clock)
    app = create_app(settings=s, container=c)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as cl:
        assert (await cl.get("/docs")).status_code == expected
        assert (await cl.get("/openapi.json")).status_code == expected
