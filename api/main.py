import asyncio
import json
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.db import get_db_path, init_db
from api.routes.assertions import router as assertions_router
from api.routes.logs import router as logs_router
from api.routes.progress import router as progress_router
from api.routes.runs import router as runs_router
from api.routes.scenarios import router as scenarios_router

_RESULTS_DIR = Path("/data/results")
_POLL_INTERVAL_S = 10


async def _sync_completed_runs() -> None:
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id FROM runs WHERE status='RUNNING'") as cur:
            running = [row["id"] for row in await cur.fetchall()]

    for run_id in running:
        result_path = _RESULTS_DIR / f"{run_id}.json"
        if not result_path.exists():
            continue
        try:
            data = json.loads(result_path.read_text())
            status = data.get("status", "FAIL")
        except Exception:
            print(
                f"[api] could not read result for {run_id}\n{traceback.format_exc()}",
                flush=True,
            )
            status = "FAIL"

        async with aiosqlite.connect(get_db_path()) as db:
            await db.execute(
                "UPDATE runs SET status=?, updated_at=? WHERE id=?",
                (status, datetime.now(timezone.utc).isoformat(), run_id),
            )
            await db.commit()
        print(f"[api] run {run_id} → {status}", flush=True)


async def _poll_job_statuses() -> None:
    while True:
        await asyncio.sleep(_POLL_INTERVAL_S)
        try:
            await _sync_completed_runs()
        except Exception:
            print(f"[api] status poll error\n{traceback.format_exc()}", flush=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    task = asyncio.create_task(_poll_job_statuses())
    yield
    task.cancel()


app = FastAPI(title="Kratos", version="0.1.0", lifespan=lifespan)
app.include_router(scenarios_router)
app.include_router(runs_router)
app.include_router(logs_router)
app.include_router(assertions_router)
app.include_router(progress_router)

_ui_dist = Path(__file__).parent.parent / "ui" / "dist"
if _ui_dist.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dist), html=True), name="ui")
