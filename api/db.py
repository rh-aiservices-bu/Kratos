import os
from pathlib import Path

import aiosqlite


def get_db_path() -> str:
    return os.environ.get("DB_PATH", "/data/kratos.db")


async def init_db() -> None:
    path = get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id               TEXT PRIMARY KEY,
                scenario         TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'PENDING',
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                config_overrides TEXT
            )
            """
        )
        # Migration: add config_overrides column to existing databases
        try:
            await db.execute("ALTER TABLE runs ADD COLUMN config_overrides TEXT")
        except Exception:
            pass  # column already exists
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS task_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL REFERENCES runs(id),
                task_name   TEXT NOT NULL,
                status      TEXT NOT NULL,
                duration_ms REAL,
                error       TEXT
            )
            """
        )
        await db.commit()
