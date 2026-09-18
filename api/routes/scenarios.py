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
                "config": raw.get("config", {}),
                # A scenario with no explicit category (e.g. one someone
                # writes themselves) lands in "Custom" automatically — the
                # UI always shows that bucket, so this is the only default
                # needed to make it "just work".
                "category": raw.get("category") or "Custom",
            }
        )
    return result
