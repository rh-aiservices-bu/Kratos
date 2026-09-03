# Kratos - RHOAI MaaS Testing Harness

## Context

A testing harness for Red Hat OpenShift AI (RHOAI) Models as a Service (MaaS). Validates existing RHOAI environments by running test scenarios against live endpoints. The harness user will typically be an admin, but uses RHOAI's dedicated endpoints and functionality as intended (not bypassing RHOAI's own access controls — acting through RHOAI's user-facing APIs, not raw cluster admin operations).

Tests are composed of atomic **tasks** (e.g., provision API key, send inference requests) grouped into **scenarios** (user-selectable flows defined in YAML). The harness runs in-cluster as Kubernetes Jobs, orchestrated by a web UI accessed via an OpenShift Route.

## Architecture Overview

```
                  Browser UI (HTML/JS)
                  - Pick scenario, start run
                  - Live log streaming (SSE)
                  - Results history
                          |
                  FastAPI Backend (Deployment)
                  - Serve UI static files
                  - GET  /api/scenarios
                  - POST /api/runs
                  - GET  /api/runs, /api/runs/{id}
                  - GET  /api/runs/{id}/logs  (SSE)
                  - Creates K8s Jobs, watches pod logs
                  - SQLite run history on PVC
                          |
                  Kubernetes Job (one per run)
                  - Loads scenario YAML
                  - Executes tasks in order
                  - Runs cleanup automatically after each run
                  - Writes results to PVC
```

## Repository Structure

```
kratos/
├── harness/                    # Test runner (K8s Job entrypoint)
│   ├── __init__.py
│   ├── main.py                 # Job entrypoint: load scenario, run tasks, cleanup
│   ├── runner.py               # ScenarioRunner: orchestrates tasks, records results
│   ├── result.py               # RunResult dataclass (task results, timing, status)
│   └── tasks/
│       ├── __init__.py
│       ├── base.py             # Task base class: abstract run() + cleanup()
│       ├── auth.py             # simulate_login, provision_api_key
│       ├── inference.py        # send_requests (OpenAI-compat), load over period
│       ├── metrics.py          # fill_metrics_store, test_historic_metadata
│       └── registry.py         # task name -> class mapping for YAML resolution
│
├── scenarios/                  # YAML scenario definitions
│   ├── stress_test.yaml
│   ├── key_provisioning.yaml
│   └── metrics_fill.yaml
│
├── api/                        # FastAPI backend
│   ├── __init__.py
│   ├── main.py
│   ├── db.py                   # SQLite (aiosqlite)
│   ├── k8s.py                  # Create/watch Jobs via kubernetes Python client
│   └── routes/
│       ├── scenarios.py
│       ├── runs.py
│       └── logs.py             # SSE log streaming
│
├── ui/                         # Frontend (static files served by FastAPI)
│   ├── index.html
│   ├── app.js                  # Vanilla JS: scenario list, run trigger, SSE logs
│   └── styles.css
│
├── deploy/                     # OpenShift/K8s manifests
│   ├── serviceaccount.yaml
│   ├── rbac.yaml               # Role: create/get/watch Jobs + Pods
│   ├── pvc.yaml                # PVC for SQLite DB + results
│   ├── configmap.yaml          # Scenario YAMLs mounted into jobs
│   ├── deployment.yaml         # API server
│   ├── service.yaml
│   └── route.yaml              # OpenShift Route
│
├── Dockerfile                  # Single image for both API server and job runner
├── Makefile                    # build, push, deploy, dev
├── pyproject.toml              # deps: fastapi, uvicorn, kubernetes, aiosqlite, httpx, openai
└── README.md
```

## Key Design Decisions

### Single Container Image
Both the API server and the harness job use the same image, different entrypoints:
- API server: `uvicorn api.main:app`
- Job runner: `python -m harness.main --scenario <name> --run-id <uuid>`

### Task Model
```python
class Task(ABC):
    async def run(self, ctx: TaskContext) -> TaskResult: ...
    async def cleanup(self, ctx: TaskContext) -> None: ...
```
`TaskContext` carries: model endpoint URL, API key, run config, shared state dict.

### Scenario YAML Format
```yaml
name: stress_test
description: "Send many requests to a model endpoint"
config:
  model_endpoint: "${MODEL_ENDPOINT}"   # env var substitution at runtime
  api_key: "${API_KEY}"
  model_name: "${MODEL_NAME}"
tasks:
  - name: provision_api_key
    params:
      key_name: "kratos-test-key"
  - name: send_requests
    params:
      count: 1000
      concurrency: 10
      prompt: "Hello, world!"
cleanup: automatic   # tasks' cleanup() always runs after scenario (pass or fail)
```

### Results Storage
- SQLite on PVC at `/data/kratos.db` (tables: `runs`, `task_results`)
- Run results JSON also written to `/data/results/<run-id>.json`

### Log Streaming
- API server streams pod logs via `kubernetes` Python client -> SSE to browser
- UI reconnects automatically if SSE drops

### Cleanup
- Every task's `cleanup()` runs after the scenario regardless of pass/fail
- Cleanup failures are logged but do not mark the run as failed
- Sensitive per-run K8s Secrets (API keys passed to jobs) are deleted after the job completes

### Auth to RHOAI
- Model endpoint URL and API key passed to the job via K8s Secret (created per-run, deleted after)
- Scenario YAML uses `${ENV_VAR}` placeholders resolved at job runtime

## Scenarios (v1)

| Scenario | Tasks |
|---|---|
| `stress_test` | provision key -> send N concurrent requests -> cleanup key |
| `key_provisioning` | simulate login -> provision N API keys -> verify each -> cleanup all |
| `metrics_fill` | provision key -> fill metrics store -> test historic metadata query -> cleanup |

## Open Questions

- How many groups can a user have in a subscription?
- How many external models can a subscription have?

## Implementation Order

1. `pyproject.toml` + `Dockerfile` (project skeleton)
2. `harness/tasks/base.py` + `harness/tasks/registry.py`
3. Task implementations: `auth.py`, `inference.py`, `metrics.py`
4. `harness/runner.py` + `harness/main.py`
5. Scenario YAML files
6. `api/db.py` + `api/k8s.py`
7. FastAPI routes
8. UI (`index.html`, `app.js`, `styles.css`)
9. Deploy manifests
10. `Makefile` + `README.md`

## Verification

1. **Local harness**: `python -m harness.main --scenario stress_test --run-id test-123` (needs real RHOAI endpoint in env vars)
2. **API server**: `uvicorn api.main:app --reload` -> open browser, verify scenario list loads
3. **End-to-end**: Deploy to cluster, open Route URL, trigger run, watch live logs, verify results in history, verify cleanup (no leftover API keys)
4. **Unit tests**: `pytest harness/tests/` with mocked RHOAI responses
