import json
import traceback
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.db import get_db_path
from api.k8s import create_job, stop_run

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


@router.post("/api/runs/{run_id}/stop")
async def stop_run_route(run_id: str) -> dict:
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT status FROM runs WHERE id=?", (run_id,)) as cur:
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] not in ("PENDING", "RUNNING"):
        raise HTTPException(status_code=409, detail=f"Run is already {row['status']}")

    try:
        pod_found = stop_run(run_id)
    except Exception as exc:
        print(f"[api] stop_run FAILED for {run_id}\n{traceback.format_exc()}", flush=True)
        raise HTTPException(status_code=502, detail="Failed to signal the run's pod") from exc

    if not pod_found:
        # No pod yet (still PENDING) — no harness process will ever self-report,
        # so finalize the DB row directly instead of waiting on the sync poller.
        async with aiosqlite.connect(get_db_path()) as db:
            await db.execute(
                "UPDATE runs SET status='CANCELLED', updated_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), run_id),
            )
            await db.commit()
        return {"run_id": run_id, "status": "CANCELLED"}

    # Pod exists — it's up to the harness's own SIGTERM handler + cleanup + final
    # result write. api/main.py's existing _sync_completed_runs poller will pick
    # up the resulting "CANCELLED" status from that result JSON on its normal
    # cadence, same single-source-of-truth path every other terminal transition
    # already goes through — no direct DB write here avoids racing that poller.
    return {"run_id": run_id, "status": "STOPPING"}
