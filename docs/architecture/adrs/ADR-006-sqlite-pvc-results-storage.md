# ADR-006: SQLite on PVC for Run History and Results

## Status

Accepted

## Context

Kratos needs to persist run history (metadata: scenario name, start/end time, status, assertions outcome) and per-run task results so the UI can show a history view and the operator can review past runs.

Options considered:

- **In-memory only**: results are lost when the API server pod restarts. Unacceptable for an admin tool.
- **External database (PostgreSQL, etc.)**: requires provisioning and operating a separate database, adding significant infrastructure overhead for what is a single-tenant admin tool.
- **SQLite on a PVC**: a single-file database on a Kubernetes PersistentVolumeClaim. Accessed by the API server via `aiosqlite` (async). No separate infrastructure required.
- **Flat JSON files only on PVC**: no structured query support; harder to implement the runs list and filtering UI.

## Decision

Use **SQLite on a PVC** at `/data/kratos.db`. The API server reads and writes run history via `aiosqlite`. In addition, each run's full result is also written as a JSON file at `/data/results/<run-id>.json` for easy inspection without a database client.

Schema:
- `runs` table: run ID, scenario name, status, timestamps, assertion outcomes
- `task_results` table: per-task name, status, duration, output

The PVC is mounted into both the API server `Deployment` and the Job pods so both can write to it.

## Consequences

**Positive:**
- Zero external infrastructure: everything Kratos needs is in the single OCP namespace.
- `aiosqlite` integrates natively with FastAPI's async event loop.
- The JSON sidecar files at `/data/results/` are human-readable without any tooling.
- SQLite is sufficient for the access pattern: writes are infrequent (one per run), reads are by the API server only.

**Negative:**
- SQLite does not support concurrent writes from multiple processes well. If two Job pods finish and try to write results simultaneously, one will wait on the write lock. This is acceptable given the low write frequency.
- PVC must be `ReadWriteMany` (or the API server and Jobs must run on the same node with `ReadWriteOnce`). Storage class capabilities must be checked at deploy time.
- No built-in backup or point-in-time recovery. For an admin testing tool, this is acceptable.

**Neutral:**
- The database file is at `/data/kratos.db`; the PVC is mounted at `/data` in all pods.
