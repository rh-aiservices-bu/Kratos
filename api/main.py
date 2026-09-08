from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.db import init_db
from api.routes.logs import router as logs_router
from api.routes.runs import router as runs_router
from api.routes.scenarios import router as scenarios_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Kratos", version="0.1.0", lifespan=lifespan)
app.include_router(scenarios_router)
app.include_router(runs_router)
app.include_router(logs_router)

_ui_dist = Path(__file__).parent.parent / "ui" / "dist"
if _ui_dist.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dist), html=True), name="ui")
