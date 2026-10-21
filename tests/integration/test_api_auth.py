"""Integration tests for identity, session binding, and /health lifecycle."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from veltrix.api.container import reset_container
from veltrix.api.main import app
from veltrix.core.config import Settings
from veltrix.data.db import init_app_db


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path: Path) -> None:
    """Configure a clean isolated app.db for each test."""
    test_app_db = tmp_path / "test_app.db"
    settings = Settings(
        APP_DB_PATH=test_app_db,
        DB_PATH=Path("./data/veltrix.db"),
    )
    init_app_db(test_app_db)
    reset_container(settings)


@pytest.mark.asyncio
async def test_health_lifecycle() -> None:
    """Test /health returns 503 before ready, and 200 once ready."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Before ready
        app.state.ready = False
        res = await client.get("/health")
        assert res.status_code == 503
        assert res.json()["status"] == "not_ready"

        # After ready
        app.state.ready = True
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_chat_missing_employee_header_returns_401() -> None:
    """Test POST /chat returns 401 when X-Employee-Id is missing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/chat",
            json={"session_id": "sess_1", "message": "hello"},
        )
        assert res.status_code == 401
        assert "Missing X-Employee-Id" in res.json()["detail"]


@pytest.mark.asyncio
async def test_chat_unknown_employee_returns_401() -> None:
    """Test POST /chat returns 401 when employee does not exist in database."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/chat",
            headers={"X-Employee-Id": "E99999_NON_EXISTENT"},
            json={"session_id": "sess_1", "message": "hello"},
        )
        assert res.status_code == 401
        assert "not found" in res.json()["detail"]


@pytest.mark.asyncio
async def test_chat_invalid_payload_returns_400() -> None:
    """Test POST /chat returns 400 when request body is invalid or missing fields."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/chat",
            headers={"X-Employee-Id": "E1001"},
            json={"message": "missing session_id"},
        )
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_chat_session_ownership_binding_and_conflict_403() -> None:
    """Test session belongs to first caller; subsequent callers receive 403."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First call by E1001 creates and binds sess_abc
        res1 = await client.post(
            "/chat",
            headers={"X-Employee-Id": "E1001"},
            json={"session_id": "sess_abc", "message": "Initial message"},
        )
        assert res1.status_code == 200

        # Second call by same employee E1001 succeeds
        res2 = await client.post(
            "/chat",
            headers={"X-Employee-Id": "E1001"},
            json={"session_id": "sess_abc", "message": "Follow-up message"},
        )
        assert res2.status_code == 200

        # Third call by DIFFERENT employee E2001 with same session_id returns 403
        res3 = await client.post(
            "/chat",
            headers={"X-Employee-Id": "E2001"},
            json={"session_id": "sess_abc", "message": "Hijack attempt"},
        )
        assert res3.status_code == 403
        assert "owned by another employee" in res3.json()["detail"]
