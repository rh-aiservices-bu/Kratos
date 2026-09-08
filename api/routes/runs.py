import json
import traceback
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.db import get_db_path
from api.k8s import create_job

router = APIRouter()


class RunRequest(BaseModel):
    scenario: str
    config_overrides: dict = {}


@router.post("/api/runs", status_code=201)
async def create_run(body: RunRequest) -> dict:
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    overrides_json = json.dumps(body.config_overrides) if body.config_overrides else None

    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            "INSERT INTO runs (id, scenario, status, created_at, updated_at, config_overrides) VALUES (?,?,?,?,?,?)",
            (run_id, body.scenario, "PENDING", now, now, overrides_json),
        )
        await db.commit()

    status = "PENDING"
    try:
        create_job(body.scenario, run_id, body.config_overrides)
        status = "RUNNING"
    except Exception:
        print(f"[api] K8s job creation FAILED\n{traceback.format_exc()}", flush=True)

    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            "UPDATE runs SET status=?, updated_at=? WHERE id=?",
            (status, datetime.now(timezone.utc).isoformat(), run_id),
        )
        await db.commit()

    return {"run_id": run_id, "scenario": body.scenario, "status": status}


@router.get("/api/runs")
async def list_runs() -> list[dict]:
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM runs ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM runs WHERE id=?", (run_id,)) as cur:
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return dict(row)
