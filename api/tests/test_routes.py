"""API route integration tests — use in-memory SQLite and mock K8s."""
import json

import aiosqlite
import pytest


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))


@pytest.fixture()
def _mock_k8s(monkeypatch) -> None:
    import api.routes.logs
    import api.routes.runs

    monkeypatch.setattr(
        api.routes.runs, "create_job",
        lambda scenario, run_id, config_overrides=None: None,
    )
    # Log capture is a background thread that talks to a real cluster — not
    # available in this test environment. get_log_lines() reading a nonexistent
    # file already safely returns ([], False), so only this needs stubbing.
    monkeypatch.setattr(api.routes.logs, "ensure_log_capture", lambda run_id: None)


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


async def test_get_run_log_lines(client) -> None:
    r = await client.post("/api/runs", json={"scenario": "single_key_load"})
    run_id = r.json()["run_id"]

    resp = await client.get(f"/api/runs/{run_id}/logs/lines")
    assert resp.status_code == 200
    assert resp.json() == {"lines": [], "done": False, "next_offset": 0}


async def test_stop_pending_run_finalizes_immediately(client, monkeypatch) -> None:
    """No pod exists yet (stop_run returns False) — the route finalizes CANCELLED
    itself, since no harness process will ever self-report for a run that never
    got a pod."""
    import api.routes.runs

    monkeypatch.setattr(api.routes.runs, "stop_run", lambda run_id: False)

    r = await client.post("/api/runs", json={"scenario": "single_key_load"})
    run_id = r.json()["run_id"]

    resp = await client.post(f"/api/runs/{run_id}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"

    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.json()["status"] == "CANCELLED"


async def test_stop_running_run_returns_stopping_without_finalizing(client, monkeypatch) -> None:
    """A pod exists (stop_run returns True) — the route must NOT write the DB row
    itself, to avoid racing api/main.py's _sync_completed_runs poller, which is
    the single source of truth for every other terminal transition too."""
    import api.routes.runs

    monkeypatch.setattr(api.routes.runs, "stop_run", lambda run_id: True)

    r = await client.post("/api/runs", json={"scenario": "single_key_load"})
    run_id = r.json()["run_id"]

    resp = await client.post(f"/api/runs/{run_id}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "STOPPING"

    get_resp = await client.get(f"/api/runs/{run_id}")
    assert get_resp.json()["status"] == "RUNNING"


async def test_stop_unknown_run_returns_404(client) -> None:
    resp = await client.post("/api/runs/does-not-exist/stop")
    assert resp.status_code == 404


async def test_stop_already_terminal_run_returns_409(client) -> None:
    from api.db import get_db_path

    r = await client.post("/api/runs", json={"scenario": "single_key_load"})
    run_id = r.json()["run_id"]

    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute("UPDATE runs SET status='PASS' WHERE id=?", (run_id,))
        await db.commit()

    resp = await client.post(f"/api/runs/{run_id}/stop")
    assert resp.status_code == 409


async def test_get_run_config_before_written_returns_null(client) -> None:
    r = await client.post("/api/runs", json={"scenario": "single_key_load"})
    run_id = r.json()["run_id"]

    resp = await client.get(f"/api/runs/{run_id}/config")
    assert resp.status_code == 200
    assert resp.json() == {"config_yaml": None}


async def test_get_run_config_returns_yaml(client, tmp_path, monkeypatch) -> None:
    import api.routes.config

    monkeypatch.setattr(api.routes.config, "_DATA_DIR", tmp_path)
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)

    r = await client.post("/api/runs", json={"scenario": "single_key_load"})
    run_id = r.json()["run_id"]

    (tmp_path / "results" / f"{run_id}-config.json").write_text(
        json.dumps({"request_count": 5, "api_token": "***REDACTED***"})
    )

    resp = await client.get(f"/api/runs/{run_id}/config")
    assert resp.status_code == 200
    yaml_text = resp.json()["config_yaml"]
    assert "request_count: 5" in yaml_text
    assert "***REDACTED***" in yaml_text
