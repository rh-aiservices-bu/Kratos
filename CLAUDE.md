# Kratos - RHOAI MaaS Testing Harness

## Context

A testing harness for Red Hat OpenShift AI (RHOAI) Models as a Service (MaaS). Validates existing RHOAI environments by running test scenarios against live endpoints. The harness user will typically be an admin, but uses RHOAI's dedicated endpoints and functionality as intended (not bypassing RHOAI's own access controls — acting through RHOAI's user-facing APIs, not raw cluster admin operations).

Tests are composed of atomic **tasks** (e.g., provision API key, send inference requests) grouped into **scenarios** (user-selectable flows defined in YAML). The harness runs in-cluster as Kubernetes Jobs, orchestrated by a web UI accessed via an OpenShift Route.

## Architecture Overview

```
                  Browser UI (React + TypeScript + PatternFly 5)
                  - Pick scenario, override config params, start run
                  - Live log polling (REST, 1s interval) with smart scroll
                  - Live assertion status panel (2s poll, independent of logs)
                  - Task progress pipeline (2s poll)
                  - Results history + per-run detail view; URL hash routing (#run/<id>)
                          |
                  FastAPI Backend (Deployment)
                  - Serve UI static files
                  - GET  /api/scenarios
                  - POST /api/runs  (accepts config_overrides)
                  - GET  /api/runs, /api/runs/{id}
                  - GET  /api/runs/{id}/logs/lines?offset=N  (REST poll)
                  - GET  /api/runs/{id}/assertions            (reads PVC file)
                  - GET  /api/runs/{id}/progress              (reads PVC file)
                  - Creates K8s Jobs, captures pod logs to PVC
                  - SQLite run history on PVC
                          |
                  Kubernetes Job (one per run)
                  - Reads global ConfigMap + scenario YAML
                  - Executes tasks in order using SA token
                  - Background MaaS metrics poller (every 5s, if MAAS_METRICS_URL set)
                  - Runs cleanup at end (pass or fail)
                  - Writes assertions + progress to PVC in real time
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
│   ├── metrics_client.py       # fetch_metrics: shared Thanos Querier client (background poller + check_maas_metrics both use this)
│   └── tasks/
│       ├── __init__.py
│       ├── base.py             # Task ABC: run(ctx) -> TaskResult, cleanup(ctx) -> None
│       ├── auth.py             # provision_api_key  (uses SA token -> MaaS API)
│       ├── inference.py        # send_requests: concurrent OpenAI-compat load (url/token overridable)
│       ├── metrics.py          # check_maas_metrics: read MaaS metrics (total_requests, total_tokens, etc.), log summary, store in shared_state
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
│   ├── k8s.py                  # Create Jobs; background thread log capture to PVC; REST log reading
│   └── routes/
│       ├── scenarios.py        # GET /api/scenarios (includes config defaults from YAML)
│       ├── runs.py             # POST /api/runs (config_overrides), GET /api/runs, GET /api/runs/{id}
│       ├── logs.py             # GET /api/runs/{id}/logs/lines?offset=N  (REST poll, no SSE)
│       ├── assertions.py       # GET /api/runs/{id}/assertions  (reads /data/results/<id>-assertions.json)
│       └── progress.py         # GET /api/runs/{id}/progress    (reads /data/results/<id>-progress.json)
│
├── ui/                         # Frontend (React + TypeScript + PatternFly 5; built to ui/dist/)
│   ├── src/
│   │   ├── App.tsx             # Top-level: URL hash routing (#run/<id>), pushState/popstate, Kratos masthead
│   │   ├── api/client.ts       # Typed fetch wrappers for all backend API routes
│   │   ├── styles/theme.css    # Kratos/God of War dark theme: dark header, red accents, card styles
│   │   └── components/
│   │       ├── ScenarioList.tsx    # Compact scenario cards with Run button; error/retry state
│   │       ├── RunTrigger.tsx      # Config override editor (pre-filled from YAML defaults) + launch modal
│   │       ├── LogStream.tsx       # REST poll consumer (1s interval), smart scroll, "N new lines" badge
│   │       ├── AssertionPanel.tsx  # Live assertion cards (Passing/Failing/Pending) with value + expression
│   │       ├── TaskProgress.tsx    # Horizontal task pipeline chips (PENDING/RUNNING/DONE/FAIL) with progress bars
│   │       ├── RunHistory.tsx      # PatternFly Table of past runs; color-coded status badges; 3s poll while active
│   │       └── RunDetail.tsx       # Per-run detail page: metadata bar, task pipeline, logs + assertions grid
│   ├── package.json
│   └── tsconfig.json
│
├── deploy/                     # OpenShift/K8s manifests
│   ├── serviceaccount.yaml     # SA with rhoai-admin + job/pod + maassubscriptions RBAC
│   ├── rbac.yaml               # Role + RoleBinding
│   ├── rbac-monitoring.yaml    # ClusterRoleBinding: SA -> cluster-monitoring-view (Thanos Querier access)
│   ├── pvc.yaml                # PVC for SQLite DB + run results
│   ├── configmap-global.yaml   # Global cluster config (MAAS_API_URL, etc.)
│   ├── configmap-scenarios.yaml# Scenario YAML files
│   ├── deployment.yaml         # API server Deployment
│   ├── service.yaml            # ClusterIP Service
│   ├── route.yaml              # OpenShift Route (TLS edge termination)
│   └── kustomization.yaml      # oc apply -k deploy/
│
├── docs/
│   ├── architecture/
│   │   ├── adrs/                          # Architecture Decision Records (ADR-001 to ADR-014)
│   │   └── maas-metrics-reference.md      # Full catalog of MaaS/RHOAI metrics found during live-cluster research (maas-api, Limitador, vLLM, Istio, Authorino) — not just the two Kratos uses
│   └── project/
│       └── implementation-plan.md  # Phased implementation plan
│
├── Dockerfile                  # Multi-stage: Node (UI build) → Python (API + harness)
├── Makefile                    # build, push, deploy, dev, test, lint
├── pyproject.toml              # Python deps: fastapi, uvicorn, kubernetes, aiosqlite, httpx, openai
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
- `TaskContext` carries: `maas_api_url`, `sa_token`, `shared_state: dict`, resolved config, and an `emit_assertion_state()` helper
- `shared_state` is how tasks pass data forward — e.g. `provision_api_key` writes created key IDs into `shared_state["api_keys"]`; the cleanup reads and deletes them all
- Tasks report within-task progress by writing `shared_state["task_progress"] = {"current": N, "total": M}` before calling `emit_assertion_state()`. The runner snapshots and clears this once the task is *fully* done — including settling any metrics-dependent per-task assertions (see Background Metrics Polling below) — not the instant `task.run()` returns, so the UI's progress bar stays visible for the whole time a task with such assertions is settling, not just up to when its own work finished.
- `emit_assertion_state()` is called by tasks after every atomic operation that produces metric data (e.g. after each inference request in `send_requests`, after each key in `provision_api_key`). It re-evaluates all assertions against the current `shared_state` and writes the result to `/data/results/<run-id>-assertions.json` (PVC file, NOT stdout). Emission is debounced (at most every 100ms). It also writes the current task progress to `/data/results/<run-id>-progress.json`.
- **Cleanup runs after ALL tasks complete (or fail) — not per-task.** This is intentional: lets you observe the effect of many accumulated keys/resources before cleanup

### Tiered Config (three-level merge, lowest → highest precedence)

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

3. **`KRATOS_CONFIG_OVERRIDES`** env var: JSON dict injected into the Job by the API server, carrying values the user edited in the UI before launching the run. Applied at highest precedence — overrides both global ConfigMap and scenario YAML defaults.
   ```json
   {"request_count": 50, "concurrency": 2}
   ```
   `harness/config.py` reads this via `json.loads(os.environ.get("KRATOS_CONFIG_OVERRIDES", "{}"))`. The UI pre-fills the editor with YAML `config:` defaults so users see reasonable starting values.

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
  - name: send_requests
    params:
      count: "${config.request_count}"
      concurrency: "${config.concurrency}"
      prompt: "${config.prompt}"
      key_pool: true
assertions:
  error_rate_pct: "< 5"
  p99_latency_ms: "< 10000"
cleanup: automatic
```
`check_maas_metrics` is no longer a task step — MaaS metrics are polled continuously in the background by `ScenarioRunner` (see below).

### Assertions
- Evaluated continuously — after every atomic operation that produces new metric data (e.g. after each inference request in `send_requests`, after each key creation in `provision_api_key`). Result is written to `/data/results/<run-id>-assertions.json` on the PVC. **Not parsed from pod logs** — the log stream is plain text only.
- Frontend polls `GET /api/runs/{id}/assertions` every 2s independently of the log poll.
- Simple form: `metric_name: "<operator> <value>"` (operators: `<`, `>`, `<=`, `>=`, `==`)
- Match form (MaaS-vs-harness cross-check, see ADR-014): compares two live metrics to each other within a tolerance band instead of against a constant:
  ```yaml
  assertions:
    maas_requests_match:
      compare: metrics.total_requests_delta
      to: inference_results.total_requests
      tolerance_pct: 5
  ```
  `compare`/`to` are explicit `namespace.key` references. PASSING if `abs(observed - expected) <= tolerance_pct/100 * max(abs(expected), 1)`; PENDING if either side isn't populated yet.
- **PromQL form** (ADR-015): the MaaS-side value comes from a live PromQL query instead of a `shared_state` lookup, letting a scenario author write and see the actual metric check in the YAML instead of it being split across the global ConfigMap and two `result.py` code paths:
  ```yaml
  assertions:
    maas_requests_match:
      promql: >-
        abs(
          (sum(authorized_calls{limitador_namespace="${config.limitador_namespace}"}) - ${baseline.total_requests})
          - ${harness.inference_results.total_requests}
        )
        <= bool (${config.metrics_tolerance_pct} / 100 * clamp_min(${harness.inference_results.total_requests}, 1))
      expect: "== 1"        # or: compare_to: inference_results.total_requests / tolerance_pct: 5
  ```
  `${baseline.<name>}` resolves once (right after the pre-run baseline snapshot) to a value from the scenario's `metrics_queries:` block (see Background Metrics Polling below). `${harness.<namespace>.<key>}` resolves fresh on every poll tick from live `shared_state` (e.g. `inference_results.total_requests`) — if that value isn't populated yet, that tick's query is skipped and the assertion stays PENDING. Either `expect: "<op> <value>"` (same grammar as the simple form) or `compare_to`/`tolerance_pct` (same tolerance-band math as the match form) reads the already-fetched result; the query itself is fired by the runner, `harness/result.py` stays a pure synchronous evaluator. `compare`/`to` (match form) remains fully supported — `promql` is additive, not a replacement.
  **Does not solve run-scoping**: `${baseline.x}`/`${harness.x}` are numeric literal substitutions, not Prometheus labels — a `promql` assertion still can't distinguish this run's traffic from a concurrent run/caller hitting the same model route any better than the match form can (see the scoping caveat under Background Metrics Polling below).
- Available metrics from `send_requests` (via `shared_state["inference_results"]`): `error_rate_pct`, `p50/p95/p99_latency_ms`, `throughput_rps`, `total_requests`, `success_count`, `fail_count`, `total_tokens_sent`, `prompt_tokens_sent`, `completion_tokens_sent`
- Available metrics from background MaaS metrics poller (via `shared_state["metrics"]`): raw values as reported by the scenario's `metrics_queries:` block (e.g. `total_requests`, `total_tokens`), plus `{name}_delta` for each (value minus the run's baseline snapshot — see Background Metrics Polling below), plus one entry per `promql`-form assertion (keyed by assertion name). Requires `MAAS_METRICS_URL` in the global ConfigMap and at least one of `metrics_queries:`/a `promql`-form assertion in the scenario.
- Run is PASS only if all assertions pass (or no assertions defined)

### Results Storage
- SQLite on PVC at `/data/kratos.db` (tables: `runs`, `task_results`; `runs` has a `config_overrides TEXT` column)
- Run results JSON: `/data/results/<run-id>.json`
- Live assertion state: `/data/results/<run-id>-assertions.json` — written by `emit_assertion_state()`, served by `GET /api/runs/{id}/assertions`
- Live task progress: `/data/results/<run-id>-progress.json` — written by `_write_progress()` at task start/end and on each `emit()`, served by `GET /api/runs/{id}/progress`
- Pod logs: `/data/logs/<run-id>.log` (final) or `.log.tmp` (in-progress) — see Log Streaming below

### Log Streaming (REST polling — no SSE)
SSE was removed because HAProxy (OpenShift edge-terminated Routes) buffers response bodies until the connection closes, making live streaming impossible without cluster-level proxy config changes.

Current approach:
- `create_job` immediately starts a background daemon thread (`_capture_logs`) so it is already waiting for the pod before the user opens the run detail page.
- `_capture_logs` waits up to 120 s for the Job pod to appear (polling every 2 s). Once found, it polls `read_namespaced_pod_log(follow=False, _preload_content=False)` every 1 s. Each call returns the complete log from the start; the thread tracks `seen_lines` and appends only new lines to `.log.tmp`. Using `_preload_content=False` gives a raw urllib3 response that is decoded manually — the default deserializer calls `str()` on bytes, producing `b"..."` repr strings.
- When the pod phase is `Succeeded` or `Failed`, the thread does one final read then atomically renames `.log.tmp` → `.log`. The `.log` file signals "done" to readers.
- `get_log_lines(run_id, offset)` reads from `.log` (done=True) if it exists, otherwise `.log.tmp` (done=False). Returns `(new_lines[offset:], done)`.
- The frontend polls `/api/runs/{id}/logs/lines?offset=N` every 1 s, accumulates lines. Log lines are plain text only — no JSON assertion events are parsed from the log stream (assertions use their own endpoint). Polling stops when `done=true`.
- The log view uses **smart scroll**: auto-scrolls when the user is at the bottom; if scrolled up, shows a "↓ N new lines" badge that jumps back to the bottom on click.
- Log files survive pod deletion (TTL cleanup, OCP GC) since they live on the shared PVC.

### Cleanup
- Every task's `cleanup()` runs after the full scenario regardless of pass/fail
- Cleanup failures are logged but do not mark the run as failed
- No per-run K8s Secrets needed — SA token is auto-mounted; MaaS API keys are created and deleted by harness tasks themselves
- **Metrics pipeline data is not cleaned up.** MaaS metrics polling is read-only; any request traces or counters written to the RHOAI metrics pipeline during a run are intentionally left in place. Cleaning up historical metrics data is deferred to future work.
- Primary cleanup targets: MaaS API keys (bulk-revoked via `/maas-api/v1/api-keys/bulk-revoke`) and `MaaSSubscription` CRs (restored or deleted via Kubernetes API)

### SA Permissions Required
- `rhoai-admin` ClusterRole (or equivalent) — to call MaaS API
- `create`, `get`, `list`, `watch` on `jobs` and `pods` in the harness namespace
- `get` on `pods/log`
- `get`, `create`, `patch`, `delete` on `maassubscriptions` (`maas.opendatahub.io/v1alpha1`) — for `rate_limit_validation` scenario
- `cluster-monitoring-view` ClusterRole binding (`deploy/rbac-monitoring.yaml`, cluster-scoped — the only cluster-scoped grant the SA needs beyond its own namespace) — for querying Thanos Querier (background MaaS metrics polling)

## Task Reference

- **`provision_api_key`**: Calls `POST /maas-api/v1/api-keys` with the SA token. Stores created key IDs in `shared_state["api_keys"]`. Supports `count` param to create N keys in a loop; sets `shared_state["task_progress"]` after each key so the UI progress chip updates. Cleanup calls individual `DELETE /maas-api/v1/api-keys/{id}` for each created key.

- **`send_requests`**: Sends concurrent OpenAI-compatible inference requests. Resolves `url` and `token` via a three-level priority chain: (1) explicit YAML `params`, (2) `shared_state`, (3) `TaskContext` defaults (MaaS model discovery + SA token). When `key_pool: true` is set, uses keys from `shared_state["api_keys"]` and distributes requests evenly across the pool (floor(M/N) per key, remainder to first). After every completed request, updates `shared_state["inference_results"]` (latency, error count, throughput) and `shared_state["task_progress"]`, then calls `emit_assertion_state()`. Cleanup is a no-op.

- **`check_maas_metrics`**: Optional explicit final metrics check. Runs the scenario's `metrics_queries:` (via `ctx.metrics_queries`, or an explicit `params.queries` override) using the shared `harness/metrics_client.py`, stores raw values in `shared_state["metrics"]`, and prints a human-readable summary to the run log. **This task class is available for explicit use but is no longer included in standard scenario task lists.** MaaS metrics are polled automatically in the background by `ScenarioRunner` (see Background Metrics Polling below).

- **`apply_rate_limit_subscription`**: Uses `kubernetes.client.CustomObjectsApi` to create or patch a `MaaSSubscription` CR (`maas.opendatahub.io/v1alpha1`) with a configured `rps_limit`. Stores the original subscription state in `shared_state["original_subscription"]` for cleanup. Cleanup restores or deletes the CR as appropriate.

### Background Metrics Polling

MaaS/RHOAI metrics are read from Prometheus/Thanos Querier's instant-query API (`GET {MAAS_METRICS_URL}?query=<promql>`), not a MaaS-specific REST endpoint — see ADR-014 for why, and the SA RBAC (`deploy/rbac-monitoring.yaml`, `cluster-monitoring-view`) this requires. A scenario's `metrics_queries:` block (a dict of `{name: promql}` resolved for `${config.x}` like `assertions:`/task `params:`, see `scenarios/metrics_fill.yaml`) names which named PromQL queries to run — moved here from the global ConfigMap's `MAAS_METRICS_QUERIES` in ADR-015 so the query text lives next to the assertions that use it; `MAAS_METRICS_URL` itself stays global (cluster wiring). Confirmed and wired for the cluster this repo targets (`cluster-rkmhx.rkmhx.sandbox1230.opentlc.com`): Kuadrant/Limitador's gateway counters `authorized_calls` (total_requests) and `authorized_hits` (total_tokens — weighted per-token via the model's `TokenRateLimitPolicy`), both scoped by the `limitador_namespace` label (the target model's HTTPRoute name). See `docs/architecture/maas-metrics-reference.md` for the full catalog of every metric-emitting component found (not just these two) and ADR-014 for the decision. If deploying to a different cluster/model, re-verify these against a live `/api/v1/series` query rather than assuming — metric names/labels are confirmed to vary across Limitador deployments.

**Scoping caveat that applies to every form of MaaS-side assertion** (match form and PromQL form alike, ADR-014/ADR-015): no metric in the catalog carries a run-id or caller-id label — the finest grain confirmed live is `limitador_namespace`, shared by every caller of that model route. `authorized_calls`/`authorized_hits` aggregate *all* traffic on that route, not just this run's. Isolation is achieved purely by time-windowing (the baseline-delta subtraction below), never by a Prometheus label filter — a `promql`-form assertion's `${baseline.x}`/`${harness.x}` template variables are numeric literal substitutions, not labels, so they don't change this. Low risk on a dedicated single-model test sandbox; would need a caller-scoped label (if a deployed Limitador ever exposes one) on a busier shared cluster.

A `promql`-form assertion (ADR-015) fires its own ad hoc query each poll tick, in addition to the scenario's named `metrics_queries:` — `${baseline.<name>}` template variables resolve once, right after the baseline snapshot below, against a name from `metrics_queries:`; `${harness.<namespace>.<key>}` template variables resolve fresh every tick against live `shared_state` (e.g. `inference_results.total_requests`), since those values change continuously as tasks run. Both are handled in `harness/runner.py` (`_substitute_baseline_vars`, `_substitute_harness_vars`) — `harness/metrics_client.py:fetch_metrics` needed no changes, since it already accepts an arbitrary `{name: query}` dict and this just merges the per-assertion queries into the same per-tick batch as the named ones.

`ScenarioRunner.run()` takes one metrics snapshot immediately before the task loop starts and stores it as `shared_state["metrics_baseline"]`. It then starts an asyncio background task (`_metrics_bg`) that polls every 5 s, writes the raw current values into `shared_state["metrics"]`, computes `{name}_delta = current - baseline` for each metric present in both, and calls `emit()` to trigger an assertion re-evaluation. The delta — not the raw value — is what should be compared against harness-known sent counts, since the underlying Prometheus counter may be cumulative/scoped beyond a single run rather than zeroed per run.

**Settling metrics-dependent assertions** (`_settle_and_evaluate()` in `harness/runner.py`): a metrics-dependent assertion (any match-form assertion referencing `metrics.*`) can't be evaluated correctly right when its task finishes — Prometheus hasn't necessarily scraped the traffic yet (confirmed scrape interval on the cluster this repo targets: 30 s cluster-wide). So both the per-task assertion check (right after a task with `assertions:` completes) and the scenario's top-level assertion check (after cleanup) use the same mechanism: poll MaaS metrics every 5 s, re-evaluating the relevant assertions after each poll, stopping as soon as **all of them are PASSING** — or giving up at a `max_wait_s` cap (default 65 s) and reporting whatever the last evaluation showed. This directly checks the thing that actually matters (did the assertion pass) rather than inferring readiness from some proxy signal.

Three earlier designs tried to infer readiness indirectly instead, and each broke on a different, increasingly subtle behavior — see ADR-014 for the full account:
1. Stop on the first metrics value that differs from the run's original baseline — false positive on a longer run (the background poller usually already captured mid-run progress by the time the check ran).
2. Stop once two consecutive fetches return the same value ("settled") — false positive in the opposite direction (the first retry fetch usually lands within the same stale scrape window the background poller already saw).
3. Compare each metric's Prometheus sample timestamp to when the check started, using PromQL's `timestamp()` function — worked on a bare metric, but the actually-configured queries are wrapped in `sum(...)`, and aggregation functions reset a series' timestamp to query-evaluation time before `timestamp()` ever sees the original scrape time, so this also read as instantly "fresh."
4. **A separate, distinct bug found alongside these**: the very first "wait" implementation only applied to the scenario's *top-level* `assertions:` block, evaluated once after cleanup. But `metrics_fill.yaml` (like other scenarios) attaches its MaaS match-assertions to the `send_requests` *task* instead — and the per-task assertion check ran a single immediate evaluation with no retry at all, failing instantly regardless of any wait logic further down. This is why `_settle_and_evaluate()` is now shared by both call sites.

`max_wait_s` is tunable per match-assertion, since different scenarios/clusters may need more or less headroom than the default:
```yaml
assertions:
  maas_requests_match:
    compare: metrics.total_requests_delta
    to: inference_results.total_requests
    tolerance_pct: 5
    max_wait_s: 65   # optional; all metrics-dependent assertions (match-form and promql-form, ADR-015) in a scenario share one settle loop, so the max configured value across them wins
```

**Task progress stays visible while settling.** `shared_state["task_progress"]` is popped (frozen into the DONE chip's final snapshot) only *after* a task's per-task assertions finish settling, not the instant `task.run()` returns — settling can take up to `max_wait_s`, and popping it early left the UI showing the task as RUNNING but with no progress data to render for that whole window, so the progress bar vanished and only reappeared once the task was finally marked DONE (confirmed live, then fixed and covered by `test_task_progress_stays_visible_during_settle_wait` in `harness/tests/test_runner.py`).

The `check_maas_metrics` task class still exists and can be added to a scenario's task list if an explicit final check with a log summary is wanted. Standard scenarios no longer include it.

### Task Progress UI

The run detail page shows a horizontal **task pipeline** above the logs. Each chip displays:
- Status icon: `○` PENDING | CSS spinner RUNNING | `✓` DONE | `✗` FAIL
- Task name (snake_case → Title Case)
- A mini progress bar + `{current} / {total}` label when the task reports `shared_state["task_progress"]` — visible during RUNNING (including while a task's per-task assertions are settling, see Background Metrics Polling above) and preserved on completion (at 100% for DONE, actual for FAIL)

Chip background colours: grey (PENDING), blue tint (RUNNING), green (DONE), red (FAIL).

The `TaskProgress` component polls `GET /api/runs/{id}/progress` every 2 s, managing its own interval independently of logs and assertions.

## Scenarios (v1)

All five scenarios' `send_requests` assertions are now `promql`-form (ADR-015) rather than the plain string form — even where the check is a pure harness-side number (`error_rate_pct`, `p99_latency_ms`, `throughput_rps`) with no real backing Prometheus metric, the value is passed through as a `${harness.x}`-substituted literal (e.g. `promql: "${harness.inference_results.error_rate_pct}"`, `expect: "< 5"`), so every scenario run now exercises the real query-firing/parsing path against the live Thanos Querier, not just `metrics_fill`. This was a deliberate choice to broaden test coverage of the new mechanism, not a claim that these checks became more meaningful — `direct_inference` in particular bypasses the MaaS gateway entirely, so there's no real MaaS-side metric to check there regardless of form.

| Scenario | Tasks | Default Config | Default Assertions | Notes |
|---|---|---|---|---|
| `single_key_load` | provision_api_key → send_requests → [cleanup: delete key] | `request_count: 100`, `concurrency: 5` | `error_rate_pct`/`p99_latency_ms` — promql pass-through, `< 5`/`< 10000` | Baseline load test — one key, N requests through MaaS. MaaS metrics polled in background automatically. |
| `multi_key_load` | provision_api_key × N → send_requests (M reqs distributed across key pool) → [cleanup: delete all N keys] | `key_count: 5`, `request_count: 5`, `concurrency: 5` | `error_rate_pct` — promql pass-through, `< 5` | M requests distributed evenly across N keys (floor(M/N) per key, remainder to first). Default M=N so each key gets exactly 1 probe. |
| `direct_inference` | send_requests (url=target_url, token=target_token) — no key provisioning, no cleanup | `target_url: ""` (required), `target_token: ""` (required), `request_count: 50`, `concurrency: 5` | `error_rate_pct` — promql pass-through, `< 5` | Send inference directly to any configurable endpoint. Bypasses MaaS gateway — tests underlying model serving or compares MaaS-routed vs direct latency. No real MaaS-side metric applies here regardless of assertion form. |
| `rate_limit_validation` | apply_rate_limit_subscription(rps_limit) → provision_api_key × N → send_requests → [cleanup: delete keys + restore/delete MaaSSubscription] | `rate_limit_rps: 10`, `request_count: 100`, `concurrency: 20`, `key_count: 1` | `throughput_rps`/`error_rate_pct` — promql pass-through, `<= ${config.rate_limit_rps}`/`< 30` | Creates a `MaaSSubscription` CR with a configured rate limit. Fires requests and asserts observed throughput stays at or below the limit. Some 429s are expected. |
| `metrics_fill` | provision_api_key → send_requests → [cleanup: delete key] | `request_count: 200`, `concurrency: 10`, `metrics_tolerance_pct: 5` | `error_rate_pct` — promql pass-through, `< 5`; `maas_requests_match`/`maas_tokens_match` — self-contained `promql`-form assertions (ADR-015) asserting MaaS-reported request/token deltas match `inference_results.total_requests`/`total_tokens_sent` within tolerance | The canonical MaaS-vs-harness cross-check scenario (ADR-014/ADR-015) — sends a burst and asserts MaaS-reported request/token counts actually match what the harness sent, not just that they're non-zero. |

**Design note**: Tasks are kept atomic and composable so future scenarios can reuse just `provision_api_key`, just `send_requests`, etc.

## Future Features / Scenario Ideas

- **Historic metadata testing**: Pre-populate metrics store with backdated requests to simulate a year of data. Needs research into Prometheus remote-write or MaaS-specific APIs. **Requires cluster admin** — writing backdated data directly to the metrics store is not possible with rhoai-admin alone.
- **Per-user auth**: Inherit the permissions of the UI user (OIDC token passthrough) instead of always using the SA token.
- **Group limit probing**: How many groups can a user have in a subscription? Scenario that probes this limit.
- **External model enumeration**: How many external models can a subscription have? Scenario that validates external model routes (OpenAI/Bedrock/Gemini) through the MaaS gateway.

## Implementation Plan

See [`docs/project/implementation-plan.md`](docs/project/implementation-plan.md) for the full phased plan including milestones for CI, documentation, and deployment. Summary of phases:

| Phase | Scope |
|---|---|
| 0 | Project foundation: repo scaffold, pyproject.toml, package.json, Makefile, CI skeleton |
| 1 | Harness core: Task ABC, `emit_assertion_state()`, config loader, assertion evaluator, ScenarioRunner |
| 2 | Task implementations: `auth.py`, `inference.py`, `metrics.py` (stub), `subscription.py` |
| 3 | Scenario YAMLs: all five scenarios with schema validation |
| 4 | API server: FastAPI routes, SQLite, K8s job management, REST log polling |
| 5 | Frontend: React + PatternFly 5 UI — Kratos theme, scenario config editor, run detail page, live assertion panel, run history |
| 6 | Containerization: multi-stage Dockerfile, all deploy manifests, finalized Makefile |
| 7 | Integration & E2E testing on a live RHOAI cluster |
| 8 | CI/CD: lint + unit test + build on PRs; image push on release tags |
| 9 | Documentation: quickstart, scenario authoring guide, task dev guide, runbook, API reference |

## Verification

1. **Unit tests**: `make test` — runs `pytest harness/tests/` (mocked HTTP) + Jest (UI components)
2. **Local harness**: `python -m harness.main --scenario single_key_load --run-id test-123` (needs real MaaS cluster env vars)
3. **Local dev**: `make dev` — starts FastAPI dev server + Vite dev server; open browser, verify scenario list loads and assertion panel renders
4. **Build**: `make build` — multi-stage Docker build (Node UI build → Python image)
5. **End-to-end**: `make deploy` (`oc apply -k deploy/`) → open Route URL → pick scenario → edit config overrides in modal → start run → confirm task pipeline chips appear within ~2 s and update (RUNNING with progress bar → DONE green) → confirm logs stream and scroll smartly (scroll up to see "N new lines" badge) → confirm assertion panel updates independently → navigate away and back (browser back button should work via URL hash) → verify results in history → verify no leftover `kratos-*` MaaS API keys → verify `MaaSSubscription` CR state restored after `rate_limit_validation`
6. **MaaS metrics cross-check specifically**: run `metrics_fill` (needs `MAAS_METRICS_URL` set and `deploy/rbac-monitoring.yaml` applied — the scenario's own `metrics_queries:` block supplies the PromQL) → confirm `maas_requests_match`/`maas_tokens_match` go PASSING, not just `error_rate_pct` — these only appear on `metrics_fill`'s run page, not on other scenarios' (they aren't in those scenarios' `assertions:` blocks) — while settling, `send_requests`'s progress bar should stay visible the whole time rather than disappearing and popping back at the end. Confirmed working end-to-end on `cluster-rkmhx.rkmhx.sandbox1230.opentlc.com` prior to the ADR-015 migration to self-contained `promql`-form assertions — re-verify live after that change, since `clamp_min`/`bool` usage in the new query text hasn't been checked against a real Thanos Querier yet.
