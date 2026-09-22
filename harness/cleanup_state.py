"""Small PVC-file read/write helpers backing the per-run auto-cleanup toggle.

Shared between harness/runner.py (writes the run's shared_state + its own
cleanup outcome; reads the live toggle right before deciding whether to run
task cleanup) and the API server (writes the toggle at launch/on flip; reads
the persisted shared_state + outcome to sync history and to perform a manual
"Clean Up Now" after the harness process has already exited).

Every function takes `results_dir` explicitly (the same directory the caller
already writes/reads -progress.json/-assertions.json/-config.json from)
rather than hardcoding a module-level constant, so tests can point it at a
tmp_path exactly like the existing harness/runner.py tests already do for
those other files, with no extra monkeypatching required here.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

# status: "pending" (not yet reached) | "cleaning" | "skipped" (toggle was off)
# | "done" | "failed"


def _path(results_dir: Path, run_id: str, suffix: str) -> Path:
    return results_dir / f"{run_id}-{suffix}"


def read_auto_cleanup_flag(results_dir: Path, run_id: str) -> bool:
    """Defaults to True (today's unconditional-cleanup behavior) if the flag
    file is missing or unreadable — a run that predates this feature, or a
    write that hasn't landed yet, must never silently skip cleanup."""
    try:
        data = json.loads(_path(results_dir, run_id, "cleanup-flag.json").read_text())
        return bool(data.get("auto_cleanup", True))
    except (OSError, ValueError):
        return True


def write_auto_cleanup_flag(results_dir: Path, run_id: str, enabled: bool) -> None:
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        _path(results_dir, run_id, "cleanup-flag.json").write_text(
            json.dumps({"auto_cleanup": enabled}), encoding="utf-8"
        )
    except OSError as exc:
        print(f"[cleanup_state] could not write auto-cleanup flag: {exc}", flush=True)


def write_cleanup_state(results_dir: Path, run_id: str, shared_state: dict) -> None:
    """Persist shared_state so a later manual cleanup (run by the API server,
    after this process has exited) has what each task's cleanup() needs."""
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        _path(results_dir, run_id, "cleanup-state.json").write_text(
            json.dumps(shared_state, default=str), encoding="utf-8"
        )
    except OSError as exc:
        print(f"[cleanup_state] could not write cleanup state: {exc}", flush=True)


def read_cleanup_state(results_dir: Path, run_id: str) -> dict:
    try:
        return json.loads(_path(results_dir, run_id, "cleanup-state.json").read_text())
    except (OSError, ValueError):
        return {}


def write_cleanup_status(
    results_dir: Path, run_id: str, status: str, error: str | None = None
) -> None:
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
        }
        _path(results_dir, run_id, "cleanup-status.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    except OSError as exc:
        print(f"[cleanup_state] could not write cleanup status: {exc}", flush=True)


def read_cleanup_status(results_dir: Path, run_id: str) -> dict:
    try:
        return json.loads(_path(results_dir, run_id, "cleanup-status.json").read_text())
    except (OSError, ValueError):
        return {"status": "pending", "updated_at": None, "error": None}
