import os
from pathlib import Path

import yaml
from fastapi import APIRouter

router = APIRouter()


def _scenarios_dir() -> Path:
    return Path(os.environ.get("SCENARIOS_DIR", "scenarios"))


@router.get("/api/scenarios")
async def list_scenarios() -> list[dict]:
    result = []
    for f in sorted(_scenarios_dir().glob("*.yaml")):
        if f.stem.startswith("stub"):
            continue
        raw = yaml.safe_load(f.read_text())
        result.append(
            {
                "name": raw.get("name", f.stem),
                "description": raw.get("description", ""),
            }
        )
    return result
