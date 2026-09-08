"""API route integration tests — use in-memory SQLite and mock K8s."""
from collections.abc import AsyncGenerator

import pytest


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))


@pytest.fixture()
def _mock_k8s(monkeypatch) -> None:
    import api.routes.runs
    import api.routes.logs

    monkeypatch.setattr(api.routes.runs, "create_job", lambda scenario, run_id: None)

    async def _fake_stream(_run_id: str) -> AsyncGenerator[str, None]:
        yield 'data: {"event":"log","data":"hello"}\n\n'

    monkeypatch.setattr(api.routes.logs, "stream_pod_logs", _fake_stream)


@pytest.fixture()
async def client(_temp_db, _mock_k8s):
    from httpx import ASGITransport, AsyncClient

    from api.db import init_db
    from api.main import app

    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_scenarios_returns_five(client) -> None:
    resp = await client.get("/api/scenarios")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 5
    names = {s["name"] for s in data}
    assert {"single_key_load", "multi_key_load", "direct_inference"} <= names
    assert all("name" in s and "description" in s for s in data)


async def test_create_run_returns_run_id(client) -> None:
    resp = await client.post("/api/runs", json={"scenario": "single_key_load"})
    assert resp.status_code == 201
    data = resp.json()
    assert "run_id" in data
    assert data["scenario"] == "single_key_load"


async def test_list_runs_includes_created_run(client) -> None:
    r = await client.post("/api/runs", json={"scenario": "single_key_load"})
    run_id = r.json()["run_id"]

    resp = await client.get("/api/runs")
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()]
    assert run_id in ids


async def test_get_run_by_id(client) -> None:
    r = await client.post("/api/runs", json={"scenario": "single_key_load"})
    run_id = r.json()["run_id"]

    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == run_id
    assert resp.json()["scenario"] == "single_key_load"


async def test_get_nonexistent_run_returns_404(client) -> None:
    resp = await client.get("/api/runs/does-not-exist")
    assert resp.status_code == 404


async def test_get_run_logs_streams_sse(client) -> None:
    r = await client.post("/api/runs", json={"scenario": "single_key_load"})
    run_id = r.json()["run_id"]

    resp = await client.get(f"/api/runs/{run_id}/logs")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "data:" in resp.text
