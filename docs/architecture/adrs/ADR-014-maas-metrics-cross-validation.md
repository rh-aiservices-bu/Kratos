# ADR-014: MaaS Metrics Cross-Validation via Prometheus Baseline Delta

## Status

Accepted

## Context

Kratos needs to validate that what MaaS/RHOAI *reports* (total requests, total tokens — the numbers shown on the MaaS dashboard) actually reflects what the harness *knows it sent*, not merely that some metric is non-zero. This surfaced two problems in the prior design:

1. **Namespace collision**: `harness/result.py`'s assertion lookup checked `shared_state["inference_results"]` before `shared_state["metrics"]`. Since both the harness's own request counter and the MaaS-side poller wrote a key literally named `total_requests`, an assertion named `total_requests` could only ever resolve to the harness's own client-side count — it was structurally impossible to see the MaaS-reported value through it.
2. **No cross-metric comparison**: the assertion engine only supported `metric_name: "<operator> <constant>"`. There was no way to express "MaaS-reported count should equal harness-sent count."
3. **Unknown transport**: there is no confirmed MaaS-specific REST metrics endpoint. The MaaS dashboard most likely sources its numbers directly from Prometheus/Thanos, the same as any other OpenShift-monitoring-backed dashboard. The exact PromQL queries and metric names are unconfirmed and require research against a live cluster.
4. **Counter semantics are unknown**: MaaS/Prometheus counters may be cumulative (scoped to a subscription/key that persists across runs) rather than zeroed per run, so a raw post-run value can't be compared directly against "requests sent this run" without more context.

## Decision

**Transport**: query Prometheus/Thanos Querier's standard instant-query API (`GET /api/v1/query?query=<promql>`, bearer SA token) via a single consolidated client, `harness/metrics_client.py` (`fetch_metrics`), used by both the background poller (`harness/runner.py`) and the optional explicit `check_maas_metrics` task (`harness/tasks/metrics.py`) — replacing the two previously-duplicated ad hoc `httpx` GET implementations. Querying Thanos Querier requires the harness SA to be bound to the cluster's `cluster-monitoring-view` ClusterRole (`deploy/rbac-monitoring.yaml`).

Confirmed against a live cluster (`cluster-rkmhx.rkmhx.sandbox1230.opentlc.com`, the one `deploy/configmap-global.yaml` targets): `MAAS_METRICS_URL` is the Thanos Querier route, `https://thanos-querier-openshift-monitoring.apps.cluster-rkmhx.rkmhx.sandbox1230.opentlc.com/api/v1/query`. `MAAS_METRICS_QUERIES` uses Kuadrant/Limitador's gateway data-plane counters — `authorized_calls` (total_requests) and `authorized_hits` (total_tokens, via the model's `TokenRateLimitPolicy` weighting hits by actual token usage), both scoped by the `limitador_namespace` label (the model's HTTPRoute name):
```json
{"total_requests": "sum(authorized_calls{limitador_namespace=\"llm/facebook-opt-125m-simulated-kserve-route\"})",
 "total_tokens": "sum(authorized_hits{limitador_namespace=\"llm/facebook-opt-125m-simulated-kserve-route\"})"}
```
Both queries were verified live with real non-zero data. See `docs/architecture/maas-metrics-reference.md` for the full catalog of every metric-emitting component found during this research (maas-api, vLLM, Istio, Authorino) — not just the two used here — including a noted version/config discrepancy where the upstream repo's own sample dashboards assume differently-named/labeled Limitador metrics (`_total` suffix, richer labels) than what's actually deployed on this cluster. `limitador_namespace`'s exact value is a deployment-time constant tied to whichever model MaaS exposes (same spirit as `DEFAULT_MODEL`) — re-verify if the target model changes.

**Comparison method — baseline delta**: `ScenarioRunner.run()` takes one metrics snapshot immediately before task execution starts and stores it as `shared_state["metrics_baseline"]`. Each subsequent poll writes the raw current values to `shared_state["metrics"]` *and* a computed `{name}_delta = current - baseline` for every metric present in both. This is robust regardless of whether the underlying Prometheus counter is global/cumulative or scoped to a subscription/key that outlives a single run — the delta always reflects only what happened during this run.

**Drift handling — tolerance band, no wait**: rather than a settle/grace delay before the final check (which would slow every run to accommodate scrape lag), the new match-assertion type accepts a `tolerance_pct`. Comparisons pass if `abs(observed - expected) <= tolerance_pct/100 * max(abs(expected), 1)`.

**Assertion format extension**: scenario `assertions:` values may now be either the existing string form (`"< 5"`, unchanged) or a new dict form for explicit two-metric comparisons:

```yaml
assertions:
  maas_requests_match:
    compare: metrics.total_requests_delta
    to: inference_results.total_requests
    tolerance_pct: 5
```

`compare`/`to` are explicit `namespace.key` references (resolved via `_extract_namespaced`), sidestepping the namespace-collision problem entirely — the existing bare-name single-metric lookup (`_extract_metric`) is untouched and unaffected.

**Harness-side ground truth**: `send_requests` now captures `response.usage.total_tokens` from each successful inference call and accumulates it into `shared_state["inference_results"]["total_tokens_sent"]`, giving a token-count comparison target that didn't previously exist.

## Consequences

**Positive:**
- The namespace collision is fixed without changing behavior for any existing scenario's simple string-form assertions.
- `metrics_fill` becomes a genuine MaaS-vs-harness cross-check instead of a self-referential threshold on the harness's own counter.
- Delta tracking works correctly regardless of whether MaaS/Prometheus counters are per-run-scoped or cumulative — no dependency on an unverified assumption about the metrics API's filtering capability.
- One consolidated fetch client instead of two duplicated implementations.

**Negative:**
- `authorized_calls`/`authorized_hits` aggregate *all* callers hitting that route, not just Kratos's own traffic — baseline-delta isolates by time, not by caller. Low risk on the researched cluster (a dedicated MaaS test sandbox with one simulator model), but would need a caller-scoped query (if the deployed Limitador ever exposes a `user`/`subscription` label) on a busier shared cluster.
- Tolerance-band comparison means an assertion can pass despite some real drift — accepted tradeoff for run speed; the tolerance is scenario-configurable if tighter validation is later needed.
- The dict-form assertion is a second code path in `harness/result.py`'s evaluator; scenario authors need to know when to use which form.

**Neutral:**
- `deploy/rbac-monitoring.yaml` adds a `ClusterRoleBinding` (cluster-scoped, unlike the rest of the harness's namespaced RBAC) — the only cluster-scoped grant the harness needs beyond its namespace.
- Supersedes the metric-namespace table in ADR-004 and the assertion-format description in ADR-010, both updated alongside this ADR.
