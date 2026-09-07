# Kratos — Implementation Plan

## Overview

This document breaks the Kratos project into discrete, ordered phases. Each phase has a clear scope, a set of deliverables, and a milestone that marks completion. Phases are sized to be independently shippable — each one leaves the project in a working (if incomplete) state.

Cross-cutting concerns (documentation, CI, deployment manifests) are given their own phases rather than being treated as afterthoughts bolted onto feature phases.

---

## Phase Summary

| Phase | Name | Key Deliverable | Milestone |
|---|---|---|---|
| 0 | Project Foundation | Repo scaffold, dev tooling, CI skeleton | Repo builds and lints on CI |
| 1 | Harness Core | Task engine, config loader, assertion evaluator | Scenario runs locally against mock MaaS |
| 2 | Task Implementations | All four task classes with unit tests | All tasks pass unit tests with mocked HTTP |
| 3 | Scenario YAMLs | All five scenario definitions | Scenarios load, validate, and resolve config |
| 4 | API Server | FastAPI backend — runs, scenarios, SSE logs | API serves scenarios and streams job logs |
| 5 | Frontend | React + PatternFly UI with live assertion panel | Full UI works end-to-end in development |
| 6 | Containerization & Manifests | Dockerfile, deploy manifests, Makefile | One-command deploy to an OCP cluster |
| 7 | Integration & E2E Testing | Tests against a real RHOAI environment | All 5 scenarios pass on a live cluster |
| 8 | CI/CD Pipeline | Full automated pipeline: lint, test, build, push | CI green on every PR and merge to main |
| 9 | Documentation | README, guides, runbook, API reference | Docs reviewed and published |

---

## Phase 0 — Project Foundation

**Goal**: establish the repository structure, development tooling, and CI skeleton so all subsequent phases have a consistent base to build on.

### Deliverables

- `pyproject.toml` — Python dependencies declared: `fastapi`, `uvicorn`, `kubernetes`, `aiosqlite`, `httpx`, `openai`, `pytest`, `pytest-asyncio`
- `package.json` (frontend) — React, TypeScript, PatternFly, Vite (or Webpack), ESLint, Jest
- `.github/workflows/ci.yml` (skeleton) — lint + placeholder test job; triggers on PR and push to `main`
- `Makefile` — initial targets: `lint`, `test`, `build`, `dev`
- `.gitignore`, `pyproject.toml` `[tool.ruff]` / `[tool.mypy]` config stubs
- `docs/architecture/adrs/` — all ADRs from design phase (already done)
- `CLAUDE.md` — finalized design document (already done)

### Milestone: **Repo Foundation**

> The repository builds cleanly, linters pass on CI, and the `make dev` target starts the FastAPI dev server (returning 404s for all routes, which is expected).

### Dependencies

None — this is the starting point.

---

## Phase 1 — Harness Core

**Goal**: implement the task engine, config loader, assertion evaluator, and scenario runner without any real task logic. A scenario can be executed end-to-end using stub tasks.

### Deliverables

- `harness/tasks/base.py` — `Task` ABC (`run`, `cleanup`), `TaskContext` dataclass, `emit_assertion_state()` helper
- `harness/tasks/registry.py` — task name → class mapping; raises on unknown task names
- `harness/config.py` — two-level config merge (env vars from global ConfigMap + scenario YAML `config:` section); `${config.<key>}` interpolation in params and assertion values
- `harness/result.py` — `RunResult` dataclass; assertion evaluation engine (pending / passing / failing states, operator parsing)
- `harness/runner.py` — `ScenarioRunner`: loads scenario YAML, instantiates tasks from registry, calls `run()` in order, calls `emit_assertion_state()` after each task, calls `cleanup()` on all tasks in reverse order after scenario completes (pass or fail)
- `harness/main.py` — CLI entrypoint: `python -m harness.main --scenario <name> --run-id <uuid>`; writes `RunResult` to `/data/results/<run-id>.json`
- `harness/tests/test_config.py` — unit tests: interpolation, missing keys, override precedence
- `harness/tests/test_result.py` — unit tests: all operator types, pending detection, PASS/FAIL logic
- `harness/tests/test_runner.py` — unit tests: task ordering, cleanup on failure, assertion state progression using stub tasks

### Milestone: **Harness Core**

> `python -m harness.main --scenario <stub_scenario> --run-id test-001` runs against a stub scenario YAML, executes stub tasks, emits assertion state after each, runs cleanup, and writes a valid `RunResult` JSON. All unit tests pass.

### Dependencies

- Phase 0

---

## Phase 2 — Task Implementations

**Goal**: implement all four production task classes. Each task is independently unit-tested with mocked HTTP and Kubernetes clients.

### Deliverables

- `harness/tasks/auth.py` — `ProvisionApiKeyTask`
  - `run()`: `POST /maas-api/v1/api-keys`, appends `{id, key}` to `shared_state["api_keys"]`
  - `cleanup()`: `POST /maas-api/v1/api-keys/bulk-revoke` for all IDs in `shared_state["api_keys"]`

- `harness/tasks/inference.py` — `SendRequestsTask`
  - `run()`: concurrent OpenAI-compatible inference requests; after every completed request updates running stats in `shared_state["inference_results"]` and calls `emit_assertion_state(ctx)` (debounced: emit at most every 100ms)
  - Resolves `url` and `token` via three-level priority: explicit params → `shared_state` → `TaskContext` defaults (see ADR-012)
  - Distributes requests evenly across `key_pool` when provided
  - `cleanup()`: no-op

- `harness/tasks/metrics.py` — `CheckMaasMetricsTask`
  - `run()`: reads RHOAI/MaaS metrics endpoint; stores raw values in `shared_state["metrics"]`; always prints a formatted summary to stdout (appears in pod logs / SSE stream). Initial metrics: `total_requests`, `total_tokens`. Endpoint TBD — implement as a configurable stub that returns zeroes until the real endpoint is known.
  - `cleanup()`: no-op (metrics pipeline data is not cleaned up)

- `harness/tasks/subscription.py` — `ApplyRateLimitSubscriptionTask`
  - `run()`: reads existing `MaaSSubscription` CR (if any) into `shared_state["original_subscription"]`; creates or patches CR with configured `rps_limit` via `kubernetes.client.CustomObjectsApi`
  - `cleanup()`: restores original CR state, or deletes the CR if it was created from scratch

- `harness/tests/test_auth.py` — mocked `httpx` responses for key creation and bulk-revoke
- `harness/tests/test_inference.py` — mocked OpenAI client; asserts rolling metrics update after each request; asserts debounce behaviour; asserts key pool distribution
- `harness/tests/test_metrics.py` — mocked metrics endpoint; asserts summary is printed; asserts `shared_state["metrics"]` populated
- `harness/tests/test_subscription.py` — mocked `CustomObjectsApi`; asserts original state saved; asserts cleanup restores state

### Milestone: **Task Implementations**

> All four task classes have unit tests passing with mocked HTTP and Kubernetes clients. Each task can be instantiated and run independently in isolation.

### Dependencies

- Phase 1

---

## Phase 3 — Scenario YAMLs

**Goal**: author and validate all five scenario definitions.

### Deliverables

- `scenarios/single_key_load.yaml`
- `scenarios/multi_key_load.yaml`
- `scenarios/direct_inference.yaml`
- `scenarios/rate_limit_validation.yaml`
- `scenarios/metrics_fill.yaml`

Each YAML must:
- Declare `name`, `description`, `config` (with defaults), `tasks` (with params), `assertions`, `cleanup: automatic`
- Pass schema validation (JSON Schema or Pydantic model in `harness/config.py`)
- Resolve all `${config.<key>}` references without error when loaded by `harness/config.py`

- `harness/tests/test_scenarios.py` — parametrized test: load each scenario YAML, validate schema, resolve config, assert all task names exist in registry

### Milestone: **Scenario YAMLs**

> All five scenarios load without error, pass schema validation, and all task references resolve against the registry.

### Dependencies

- Phase 1 (config loader, registry)
- Phase 2 (task classes registered)

---

## Phase 4 — API Server

**Goal**: implement the FastAPI backend — scenario listing, run creation, run history, and SSE log streaming.

### Deliverables

- `api/db.py` — `aiosqlite` setup; schema migrations for `runs` and `task_results` tables; `init_db()` called at startup
- `api/k8s.py`
  - `create_job(scenario, run_id)` — builds and submits a K8s Job manifest referencing the harness image and passing `--scenario` / `--run-id` args
  - `stream_pod_logs(run_id)` — async generator: waits for pod readiness, attaches to log stream, yields lines
- `api/routes/scenarios.py` — `GET /api/scenarios`: reads all YAML files from the scenarios ConfigMap mount; returns name, description, default config per scenario
- `api/routes/runs.py`
  - `POST /api/runs`: creates Job, writes run record to SQLite, returns run ID
  - `GET /api/runs`: returns paginated run history from SQLite
  - `GET /api/runs/{id}`: returns single run record including task results and assertion outcomes
- `api/routes/logs.py` — `GET /api/runs/{id}/logs`: SSE endpoint; wraps `k8s.stream_pod_logs()` in a `StreamingResponse`; emits both raw log lines and structured assertion state events
- `api/main.py` — FastAPI app; mounts routes; mounts `ui/dist/` as static files; calls `init_db()` on startup
- `api/tests/test_routes.py` — integration tests with mocked Kubernetes client and in-memory SQLite

### Milestone: **API Server**

> `uvicorn api.main:app --reload` starts cleanly. `GET /api/scenarios` returns all five scenarios. `POST /api/runs` creates a Job (verified against mocked K8s client). `GET /api/runs/{id}/logs` streams log lines via SSE. All route tests pass.

### Dependencies

- Phase 3 (scenarios must exist to be listed)

---

## Phase 5 — Frontend

**Goal**: implement the React + TypeScript + PatternFly UI.

### Deliverables

- `ui/` — Vite project scaffold with TypeScript, PatternFly, ESLint, Jest configured
- `ui/src/api/client.ts` — typed fetch wrappers for all backend API routes
- `ui/src/components/ScenarioList.tsx` — PatternFly `DataList` or `Gallery` of available scenarios with name, description, and a "Run" button per scenario
- `ui/src/components/RunTrigger.tsx` — modal or panel to confirm and start a run; accepts the scenario name
- `ui/src/components/LogStream.tsx` — `EventSource` consumer; renders log lines in a scrolling `CodeBlock`; auto-scrolls to bottom; reconnects on drop
- `ui/src/components/AssertionPanel.tsx` — live assertion status panel; parses structured assertion SSE events; renders each assertion as Passing / Failing / Pending with PatternFly status icons; updates after every SSE event
- `ui/src/components/RunHistory.tsx` — PatternFly `Table` of past runs with scenario name, status, timestamps, and a link to view logs
- `ui/src/App.tsx` — top-level layout: nav, scenario list, run history tabs
- `ui/src/tests/` — Jest + React Testing Library unit tests for each component

### Milestone: **Frontend**

> `make dev` starts both the FastAPI server and the Vite dev server. Navigating to the UI shows the scenario list, triggering a run streams live logs and updates the assertion panel in real-time, and the run history table reflects completed runs.

### Dependencies

- Phase 4 (API must exist for the UI to call)

---

## Phase 6 — Containerization & Deploy Manifests

**Goal**: package the project as a single container image and write all OpenShift manifests needed for a production deployment.

### Deliverables

**Dockerfile** (multi-stage):
1. `node-builder` stage — installs npm deps, runs `npm run build`, outputs `ui/dist/`
2. `python-builder` stage (optional) — installs Python deps into a virtualenv
3. Final stage — copies virtualenv + `ui/dist/` + Python source; sets default CMD to `uvicorn api.main:app`

**Deploy manifests** (`deploy/`):
- `serviceaccount.yaml` — `kratos-runner` SA
- `rbac.yaml` — Role with `jobs`, `pods`, `pods/log` permissions + `maassubscriptions` CRD permissions; ClusterRoleBinding for `rhoai-admin`
- `pvc.yaml` — PVC for `/data` (SQLite + results); `ReadWriteMany` storage class noted
- `configmap-global.yaml` — `MAAS_API_URL`, `DEFAULT_MODEL`, `DEFAULT_SUBSCRIPTION`
- `configmap-scenarios.yaml` — all five scenario YAMLs embedded
- `deployment.yaml` — API server Deployment; mounts PVC and both ConfigMaps; resource limits set
- `service.yaml` — ClusterIP Service on port 8000
- `route.yaml` — OpenShift Route with TLS edge termination
- `kustomization.yaml` — ties all manifests together for `oc apply -k deploy/`

**Makefile** — finalized targets:
- `make build` — Docker build
- `make push` — push to registry
- `make deploy` — `oc apply -k deploy/`
- `make dev` — local dev servers (FastAPI + Vite)
- `make test` — run Python and JS test suites
- `make lint` — ruff + mypy + eslint

### Milestone: **Deployable**

> `make build && make push && make deploy` deploys Kratos to an OCP cluster. The Route is accessible, the scenario list loads, and a run can be triggered from the UI and completes successfully.

### Dependencies

- Phase 5 (frontend must be built into `ui/dist/`)

---

## Phase 7 — Integration & End-to-End Testing

**Goal**: validate all five scenarios against a real RHOAI/MaaS environment.

### Deliverables

- `harness/tests/integration/` — integration test suite; requires real cluster env vars; skipped in unit test CI job
  - `test_single_key_load.py` — triggers scenario, polls for completion, asserts PASS and no leftover `kratos-*` API keys
  - `test_multi_key_load.py` — same; asserts all N keys created and all N keys revoked
  - `test_direct_inference.py` — same; asserts no API keys created or revoked
  - `test_rate_limit_validation.py` — same; asserts `MaaSSubscription` CR restored to original state
  - `test_metrics_fill.py` — same; asserts `total_requests` and `total_tokens` in `shared_state["metrics"]` are non-zero
- End-to-end checklist (manual):
  - [ ] Open Route URL in browser
  - [ ] Trigger each of the 5 scenarios
  - [ ] Confirm live logs appear during run
  - [ ] Confirm assertion panel updates in real-time
  - [ ] Confirm run appears in history after completion
  - [ ] Confirm no leftover `kratos-*` MaaS API keys after run
  - [ ] Confirm `MaaSSubscription` CR state restored after `rate_limit_validation`

### Milestone: **E2E Validated**

> All five scenarios complete with PASS status on a live RHOAI cluster. No test artifacts remain after any run. Manual checklist signed off.

### Dependencies

- Phase 6 (deployed to a cluster)

---

## Phase 8 — CI/CD Pipeline

**Goal**: automate the full build, test, and release pipeline.

### Deliverables

- `.github/workflows/ci.yml` — triggered on PRs and pushes to `main`:
  - `lint` job — ruff, mypy, eslint
  - `unit-test` job — `pytest harness/tests/` (excluding `integration/`) + Jest
  - `build` job — Docker build (no push on PRs); depends on lint + unit-test
- `.github/workflows/release.yml` — triggered on version tags (`v*`):
  - Builds and pushes image tagged with git SHA and semver tag
  - Updates `deploy/deployment.yaml` image tag and commits back (or emits an artifact)
- Image registry configuration — documented in `docs/project/registry-setup.md`
- Branch protection rules — documented: `main` requires CI green + 1 review before merge
- `.github/workflows/integration.yml` (optional) — manual-trigger workflow for integration tests against a real cluster; requires cluster kubeconfig secret

### Milestone: **CI Green**

> Every PR triggers lint + unit tests + build. Merging to `main` succeeds only when all checks pass. Tagging a release automatically builds and pushes the versioned image.

### Dependencies

- Phase 7 (all tests must exist before CI can run them)

---

## Phase 9 — Documentation

**Goal**: produce complete, reviewed documentation for operators, developers, and scenario authors.

### Deliverables

- `README.md` — project overview, architecture diagram, quickstart (deploy + first run), links to detailed docs
- `docs/project/implementation-plan.md` — this document (already done)
- `docs/architecture/adrs/` — all ADRs (already done)
- `docs/guides/quickstart.md` — step-by-step: prerequisites, `make deploy`, verify the Route, trigger a scenario, read results
- `docs/guides/scenario-authoring.md` — how to write a new scenario YAML: format reference, available tasks and their params, assertion syntax, config interpolation, adding a scenario to the ConfigMap
- `docs/guides/task-development.md` — how to add a new task class: implementing the `Task` ABC, registering in `registry.py`, writing unit tests with mocked HTTP, adding `emit_assertion_state()` calls
- `docs/guides/troubleshooting.md` — common failure modes: pod scheduling delays, PVC not bound, MaaS API auth failures, leftover resources, SSE disconnects
- `docs/reference/api.md` — FastAPI OpenAPI spec (auto-generated; link to `/docs` on the running server) + human-readable summary of each endpoint
- `docs/reference/scenario-schema.md` — full YAML schema reference with all fields, types, defaults, and examples

### Milestone: **Documentation Complete**

> All docs are written, internally linked, and reviewed. A new team member can deploy Kratos, trigger a scenario, and author a new scenario using only the published documentation.

### Dependencies

- Phase 7 (docs must reflect final, tested behaviour)

---

## Dependency Graph

```
Phase 0 (Foundation)
    └── Phase 1 (Harness Core)
            └── Phase 2 (Task Implementations)
                    └── Phase 3 (Scenario YAMLs)
                            └── Phase 4 (API Server)
                                    └── Phase 5 (Frontend)
                                            └── Phase 6 (Containerization)
                                                    └── Phase 7 (E2E Testing)
                                                            ├── Phase 8 (CI/CD)
                                                            └── Phase 9 (Documentation)
```

---

## Notes

- **`check_maas_metrics` stub**: the metrics endpoint is TBD. Phase 2 implements the task as a configurable stub that returns zeroes. The real implementation is slotted for Phase 7 when a live cluster is available to determine the actual endpoint and response schema.
- **Frontend build in Dockerfile**: the multi-stage Dockerfile in Phase 6 means the frontend must reach a buildable state (Phase 5) before the final image can be produced.
- **Integration tests** (Phase 7) require cluster access and are excluded from the standard CI unit-test job. They run in a separate manual-trigger workflow.
- **PVC storage class**: `ReadWriteMany` is assumed. If the target cluster only supports `ReadWriteOnce`, the API server and Job pods must be colocated on the same node, which constrains scheduling. This should be validated in Phase 6.
