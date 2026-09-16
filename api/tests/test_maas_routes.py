"""API route tests for /api/maas/* — mocks api.maas_client entirely so these
don't need a real cluster (see api/tests/test_maas_client.py for the parsing
logic these routes are thin wrappers around)."""
from unittest.mock import patch

import pytest

from api import maas_client


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))


@pytest.fixture()
async def client(_temp_db):
    from httpx import ASGITransport, AsyncClient

    from api.db import init_db
    from api.main import app

    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_subscriptions_available(client) -> None:
    fake = maas_client.ResourceList(available=True, items=[{"name": "simulator-free"}])
    with patch.object(maas_client, "list_subscriptions", return_value=fake):
        resp = await client.get("/api/maas/subscriptions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["items"] == [{"name": "simulator-free"}]


async def test_subscriptions_unavailable_reports_reason_not_error(client) -> None:
    fake = maas_client.ResourceList(available=False, reason="forbidden")
    with patch.object(maas_client, "list_subscriptions", return_value=fake):
        resp = await client.get("/api/maas/subscriptions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["reason"] == "forbidden"
    assert body["items"] == []


async def test_models_available(client) -> None:
    fake = maas_client.ResourceList(available=True, items=[{"name": "facebook-opt-125m-simulated"}])
    with patch.object(maas_client, "list_models", return_value=fake):
        resp = await client.get("/api/maas/models")

    assert resp.status_code == 200
    assert resp.json()["items"] == [{"name": "facebook-opt-125m-simulated"}]


async def test_access_available(client) -> None:
    fake = maas_client.ResourceList(available=True, items=[{"name": "team-a"}])
    with patch.object(maas_client, "list_access", return_value=fake):
        resp = await client.get("/api/maas/access")

    assert resp.status_code == 200
    assert resp.json()["items"] == [{"name": "team-a"}]


async def test_status_reports_per_section_availability(client) -> None:
    subs = maas_client.ResourceList(available=False, reason="forbidden")
    models = maas_client.ResourceList(available=True, items=[])
    access = maas_client.ResourceList(available=False, reason="forbidden")
    with patch.object(maas_client, "list_subscriptions", return_value=subs), \
         patch.object(maas_client, "list_models", return_value=models), \
         patch.object(maas_client, "list_access", return_value=access):
        resp = await client.get("/api/maas/status")

    assert resp.status_code == 200
    sections = resp.json()["sections"]
    assert sections["subscriptions"] == {"available": False, "reason": "forbidden"}
    assert sections["models"] == {"available": True, "reason": None}
    assert sections["access"] == {"available": False, "reason": "forbidden"}
