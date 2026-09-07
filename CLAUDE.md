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
                  - Reads global ConfigMap + scenario YAML
                  - Executes tasks in order using SA token
                  - Runs cleanup at end (pass or fail)
                  - Writes results to PVC
```

## MaaS API (key facts)

- **Base URL**: `https://maas.${CLUSTER_DOMAIN}` (cluster domain from `kubectl get ingresses.config.openshift.io cluster -o jsonpath='{.spec.domain}'`)
- **Auth**: OpenShift bearer token — SA token auto-mounted at `/var/run/secrets/kubernetes.io/serviceaccount/token`
- **Key creation**: `POST /maas-api/v1/api-keys` → returns `{ id, key (sk-oai-...), name, subscription, expiresAt }`
- **Key search**: `POST /maas-api/v1/api-keys/search`
- **Key revoke**: `DELETE /maas-api/v1/api-keys/{id}` or `POST /maas-api/v1/api-keys/bulk-revoke`
- **Model discovery**: `GET /v1/models` → `{ data: [{ id, url }] }`
- **Inference**: `POST ${MODEL_URL}/v1/chat/completions` (OpenAI-compatible, auth with `sk-oai-*` key)
- **Subscriptions**: No REST API for creating/modifying subscriptions. Rate limits are configured via the `MaaSSubscription` CRD (`maas.opendatahub.io/v1alpha1`). Use `kubernetes.client.CustomObjectsApi` to apply/patch these objects. The MaaS REST API is for api-key lifecycle only.

## Repository Structure

```
kratos/
├── harness/                    # Test runner (K8s Job entrypoint)
│   ├── __init__.py
│   ├── main.py                 # Job entrypoint: load config, run scenario, cleanup
│   ├── runner.py               # ScenarioRunner: executes tasks, records results
│   ├── result.py               # RunResult dataclass + assertion evaluation
│   ├── config.py               # Config loader: merges global ConfigMap + scenario YAML
│   └── tasks/
│       ├── __init__.py
│       ├── base.py             # Task ABC: run(ctx) -> TaskResult, cleanup(ctx) -> None
│       ├── auth.py             # provision_api_key  (uses SA token -> MaaS API)
│       ├── inference.py        # send_requests: concurrent OpenAI-compat load (url/token overridable)
│       ├── metrics.py          # check_metrics: read RHOAI/MaaS metrics, log summary, store in shared_state
│       ├── subscription.py     # apply_rate_limit_subscription: create/patch MaaSSubscription CR
│       └── registry.py         # task name -> class mapping for YAML resolution
│
├── scenarios/                  # YAML scenario definitions (mounted as ConfigMap)
│   ├── single_key_load.yaml
│   ├── multi_key_load.yaml
│   ├── direct_inference.yaml
│   ├── rate_limit_validation.yaml
│   └── metrics_fill.yaml
│
├── api/                        # FastAPI backend
│   ├── __init__.py
│   ├── main.py                 # FastAPI app, mounts static UI
│   ├── db.py                   # SQLite setup (aiosqlite)
│   ├── k8s.py                  # Create/watch Jobs via kubernetes Python client
│   └── routes/
│       ├── scenarios.py        # GET /api/scenarios
│       ├── runs.py             # POST /api/runs, GET /api/runs, GET /api/runs/{id}
│       └── logs.py             # GET /api/runs/{id}/logs  (SSE, streams pod logs)
│
├── ui/                         # Frontend (static files served by FastAPI)
│   ├── index.html
│   ├── app.js                  # Vanilla JS: scenario list, run trigger, SSE logs
│   └── styles.css
│
├── deploy/                     # OpenShift/K8s manifests
│   ├── serviceaccount.yaml     # SA with rhoai-admin + job/pod RBAC
│   ├── rbac.yaml               # Role + RoleBinding
│   ├── pvc.yaml                # PVC for SQLite DB + run results
│   ├── configmap-global.yaml   # Global cluster config (MAAS_API_URL, etc.)
│   ├── configmap-scenarios.yaml# Scenario YAML files
│   ├── deployment.yaml         # API server Deployment
│   ├── service.yaml            # ClusterIP Service
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
- `TaskContext` carries: `maas_api_url`, `sa_token`, `shared_state: dict`, resolved config
- `shared_state` is how tasks pass data forward — e.g. `provision_api_key` writes created key IDs into `shared_state["api_keys"]`; the cleanup reads and deletes them all
- **Cleanup runs after ALL tasks complete (or fail) — not per-task.** This is intentional: lets you observe the effect of many accumulated keys/resources before cleanup

### Tiered Config (two-level merge)

1. **Global ConfigMap** (`configmap-global.yaml`): cluster-level defaults, injected as env vars into every Job
   ```yaml
   MAAS_API_URL: "https://maas.apps.mycluster.example.com"
   DEFAULT_MODEL: "granite-3-8b-instruct"
   DEFAULT_SUBSCRIPTION: ""   # empty = auto-select highest priority
   ```

2. **Scenario YAML** `config:` section: per-scenario params (override globals where they overlap)
   ```yaml
   config:
     request_count: 1000
     concurrency: 10
     prompt: "Summarize this in one sentence."
   ```

### Scenario YAML Format
```yaml
name: single_key_load
description: "Baseline load test — one key, N requests through MaaS"
config:
  request_count: 100
  concurrency: 5
  prompt: "Hello, world!"
tasks:
  - name: provision_api_key
    params:
      key_name: "kratos-load-key"
      ephemeral: true
  - name: send_requests
    params:
      count: "${config.request_count}"
      concurrency: "${config.concurrency}"
      prompt: "${config.prompt}"
  - name: check_metrics
assertions:
  error_rate_pct: "< 5"
  p99_latency_ms: "< 10000"
cleanup: automatic
```

### Assertions
- Evaluated after all tasks complete
- Format: `metric_name: "<operator> <value>"` (operators: `<`, `>`, `<=`, `>=`, `==`)
- Available metrics: `error_rate_pct`, `p50/p95/p99_latency_ms`, `throughput_rps`, `total_requests`, `success_count`, `fail_count`
- Run is PASS only if all assertions pass (or no assertions defined)

### Results Storage
- SQLite on PVC at `/data/kratos.db` (tables: `runs`, `task_results`)
- Run results JSON also written to `/data/results/<run-id>.json`

### Log Streaming
- API server tails pod logs via `kubernetes` Python client → SSE to browser
- UI reconnects automatically if SSE drops

### Cleanup
- Every task's `cleanup()` runs after the full scenario regardless of pass/fail
- Cleanup failures are logged but do not mark the run as failed
- No per-run K8s Secrets needed — SA token is auto-mounted; MaaS API keys are created and deleted by harness tasks themselves

### SA Permissions Required
- `rhoai-admin` cluster role (or equivalent) to call MaaS API
- `create`, `get`, `list`, `watch` on `jobs` and `pods` in the harness namespace
- `get` on `pods/log`

## Task Reference

- **`provision_api_key`**: Calls `POST /maas-api/v1/api-keys` with the SA token. Stores created key IDs in `shared_state["api_keys"]`. Can be called multiple times to accumulate a pool of keys. Cleanup calls `POST /maas-api/v1/api-keys/bulk-revoke` to delete all created keys.

- **`send_requests`**: Sends concurrent OpenAI-compatible inference requests. Accepts optional `url` and `token` params to override context defaults — enables `direct_inference` without a separate task class. When `key_pool` param is set (list of api keys from `shared_state["api_keys"]`), distributes requests evenly across the pool. Records latency, error rate, and throughput into `shared_state["inference_results"]` for assertion evaluation.

- **`check_metrics`**: Reads the RHOAI/MaaS metrics endpoint (TBD), stores raw values in `shared_state["metrics"]` for assertion evaluation, and always prints a formatted human-readable summary to the run log — regardless of assertion pass/fail. Used as a final validation step in all MaaS-based scenarios (1, 2, 4, 5). Not used in `direct_inference` since it bypasses MaaS.

- **`apply_rate_limit_subscription`**: Uses `kubernetes.client.CustomObjectsApi` to create or patch a `MaaSSubscription` CR (`maas.opendatahub.io/v1alpha1`) with a configured `rps_limit`. Stores the original subscription state in `shared_state["original_subscription"]` for cleanup. Cleanup restores or deletes the CR as appropriate.

## Scenarios (v1)

| Scenario | Tasks | Default Config | Default Assertions | Notes |
|---|---|---|---|---|
| `single_key_load` | provision_api_key → send_requests → check_metrics → [cleanup: delete key] | `request_count: 100`, `concurrency: 5` | `error_rate_pct: "< 5"`, `p99_latency_ms: "< 10000"` | Baseline load test — one key, N requests through MaaS. Validates inference and confirms metrics are populated. Replaces `stress_test`. |
| `multi_key_load` | provision_api_key × N → send_requests (M reqs distributed across key pool) → check_metrics → [cleanup: bulk-revoke all N keys] | `key_count: 5`, `request_count: 5`, `concurrency: 5` | `error_rate_pct: "< 5"` | M requests distributed evenly across N keys (floor(M/N) per key, remainder to first). Default M=N so each key gets exactly 1 probe. All keys accumulate before cleanup — intentional. Replaces `key_provisioning`. |
| `direct_inference` | send_requests (url=target_url, token=target_token) — no key provisioning, no cleanup | `target_url: ""` (required), `target_token: ""` (required), `request_count: 50`, `concurrency: 5` | `error_rate_pct: "< 5"` | Send inference directly to any configurable endpoint with a configurable auth token. Bypasses MaaS gateway — tests underlying model serving or compares MaaS-routed vs direct latency. |
| `rate_limit_validation` | apply_rate_limit_subscription(rps_limit) → provision_api_key × N → send_requests → check_metrics → [cleanup: delete keys + restore/delete MaaSSubscription] | `rate_limit_rps: 10`, `request_count: 100`, `concurrency: 20`, `key_count: 1` | `throughput_rps: "<= ${config.rate_limit_rps}"`, `error_rate_pct: "< 30"` | Creates a `MaaSSubscription` CR with a configured rate limit. Fires requests and asserts observed throughput stays at or below the limit. Metrics step confirms 429s are reflected in the metrics pipeline. Some 429s are expected. |
| `metrics_fill` | provision_api_key → send_requests → check_metrics → [cleanup: delete key] | `request_count: 200`, `concurrency: 10` | `error_rate_pct: "< 5"`, `metrics_request_count: ">= ${config.request_count * 0.95}"` | Sends a burst then reads and validates RHOAI/MaaS metrics. Confirms the metrics pipeline is populated correctly and counters are consistent with what was sent. `check_metrics` always prints a human-readable summary to logs regardless of assertion pass/fail. |

**Design note**: Tasks are kept atomic and composable so future scenarios can reuse just `provision_api_key`, just `send_requests`, etc.

## Future Features / Scenario Ideas

- **Historic metadata testing**: Pre-populate metrics store with backdated requests to simulate a year of data. Needs research into Prometheus remote-write or MaaS-specific APIs. **Requires cluster admin** — writing backdated data directly to the metrics store is not possible with rhoai-admin alone.
- **Per-user auth**: Inherit the permissions of the UI user (OIDC token passthrough) instead of always using the SA token.
- **Scenario config in UI**: Let users tweak per-scenario params (request count, concurrency) from the browser without editing YAML.
- **Group limit probing**: How many groups can a user have in a subscription? Scenario that probes this limit.
- **External model enumeration**: How many external models can a subscription have? Scenario that validates external model routes (OpenAI/Bedrock/Gemini) through the MaaS gateway.

## Implementation Order

1. `pyproject.toml` + `Dockerfile` (project skeleton)
2. `harness/tasks/base.py` + `harness/tasks/registry.py` + `harness/config.py`
3. Task implementations: `auth.py`, `inference.py`, `metrics.py` (stub)
4. `harness/result.py` (assertion evaluation)
5. `harness/runner.py` + `harness/main.py`
6. Scenario YAML files
7. `api/db.py` + `api/k8s.py`
8. FastAPI routes
9. UI (`index.html`, `app.js`, `styles.css`)
10. Deploy manifests
11. `Makefile` + `README.md`

## Verification

1. **Local harness**: `python -m harness.main --scenario single_key_load --run-id test-123` (needs real MaaS cluster env vars)
2. **API server**: `uvicorn api.main:app --reload` → open browser, verify scenario list loads
3. **End-to-end**: `oc apply -k deploy/` → open Route URL → trigger run → watch live logs → verify results in history → verify no leftover `kratos-*` MaaS API keys
4. **Unit tests**: `pytest harness/tests/` with mocked MaaS HTTP responses (httpx mock)
