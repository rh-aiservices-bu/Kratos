# MaaS/RHOAI Metrics Reference

Findings from live-cluster research (`oc` read-only calls + Thanos Querier queries against `cluster-rkmhx.rkmhx.sandbox1230.opentlc.com`, the cluster `deploy/configmap-global.yaml` targets) plus literal source from the upstream [`opendatahub-io/models-as-a-service`](https://github.com/opendatahub-io/models-as-a-service) repo. Catalogs every metric-emitting component found, not just the two Kratos currently uses (see ADR-014 for the decision and what's actually wired up).

## Access method

All of these are scraped into Prometheus and queried the same way: via **Thanos Querier**, not a direct Prometheus connection. OpenShift runs two separate Prometheus instances — the platform one (`openshift-monitoring`) and a user-workload one (`openshift-user-workload-monitoring`) — and workload metrics (Limitador, vLLM, etc.) are scraped by the *user-workload* instance specifically (confirmed via the `prometheus="openshift-user-workload-monitoring/user-workload"` label on live query results). Thanos Querier merges both into one read endpoint, which is the standard/supported way to query "any cluster metric" without needing to know which instance scraped it:

```
GET https://thanos-querier-openshift-monitoring.apps.<CLUSTER_DOMAIN>/api/v1/query?query=<promql>
Authorization: Bearer <token>
```

Requires the querying identity to be bound to the `cluster-monitoring-view` ClusterRole (`deploy/rbac-monitoring.yaml` binds the Kratos SA to it). Verified this route/RBAC pattern exists and works on the live cluster using a real bearer token.

**Scrape freshness**: confirmed `scrapeInterval: 30s` cluster-wide (`oc get prometheus -n openshift-user-workload-monitoring -o jsonpath='{.items[0].spec.scrapeInterval}'`), no per-target override on the Limitador PodMonitor. This bounds how fresh any query result can be — a request landing right after a scrape must wait up to ~30s for the next one, which is why Kratos's final metrics check retries with a settle window (`max_wait_s`, see ADR-014) rather than fetching once.

One-off debugging technique also used during research (not what Kratos uses at runtime): the Kubernetes API server can proxy directly to a pod's or service's own metrics port without Thanos or a port-forward, which is useful for a component whose metrics haven't been scraped/labeled yet:
```
oc get --raw /api/v1/namespaces/<ns>/pods/<pod-name>:<port>/proxy/metrics
oc get --raw /api/v1/namespaces/<ns>/services/http:<service-name>:<port>/proxy/metrics
```
(Note: ad-hoc `oc port-forward` did not work reliably in the research sandbox environment used for this session — the API server proxy path above was the reliable alternative.)

## Limitador (gateway data-plane traffic — what Kratos uses)

Source of the request/token counts that actually matter for validating "what did MaaS's gateway do with the requests Kratos sent." Emitted by Limitador (Kuadrant's rate-limiter, in the request path via Istio/Envoy), scraped via the `kuadrant-limitador-monitor` PodMonitor in `kuadrant-system`.

Per the canonical upstream docs page ([`observability/metrics-and-dashboards`](https://opendatahub-io.github.io/models-as-a-service/latest/observability/metrics-and-dashboards/), raw source read literally, not AI-summarized):

| Metric | Type | Documented labels | Use for |
|---|---|---|---|
| `authorized_hits` | counter | `user`, `subscription`, `model` | Billing/cost — total tokens consumed (input+output) per request; `model` label only exists on this metric |
| `authorized_calls` | counter | `user`, `subscription` | API usage — number of allowed calls |
| `limited_calls` | counter | `user`, `subscription` | Rate limiting — requests denied for exceeding quota |
| `limitador_up` | gauge | none | Limitador liveness (1 = up) |
| `datastore_partitioned` | gauge | none | Partitioned from backing datastore (0 = healthy) |
| `datastore_latency` | histogram | none | Latency to backing datastore |

Confirmed live on the target cluster (real values at time of research):
```
authorized_calls{limitador_namespace="llm/facebook-opt-125m-simulated-kserve-route"} = 51119
authorized_hits{limitador_namespace="llm/facebook-opt-125m-simulated-kserve-route"}  = 2314256
limited_calls{limitador_namespace="llm/facebook-opt-125m-simulated-kserve-route"}    = 8771
```
**Label availability differs from the docs on this deployment**: the actually-deployed Limitador here exports only `limitador_namespace` (e.g. `llm/facebook-opt-125m-simulated-kserve-route`, the model's HTTPRoute name) — no `user`/`subscription`/`model` labels at all, despite those being documented as standard. Confirmed by a direct `/api/v1/series` query, not assumed. (A metric-name suffix mismatch I originally attributed to "version skew" here was actually my own error reading a different, newer Perses dashboard file in the same repo — see "A second, inconsistent dashboard format" below; the canonical docs above match this cluster's real metric *names* exactly, just not the labels.)

(A different, unrelated MaaS sandbox cluster checked briefly during this research, `caiprod.rhoai.rh-aiservices-bu.com`, had `authorized_calls` but no `authorized_hits` series at all — metric/label availability isn't guaranteed consistent across Limitador deployments/versions, so re-verify per cluster with a live `/api/v1/series` query before wiring `MAAS_METRICS_QUERIES`, don't assume either this doc or the upstream docs.)

Official common-query examples from the docs page (token/request totals, per-model rate, top users, rate-limit ratio, latency percentiles) all use these same bare metric names — e.g. `sum by (user) (authorized_hits)`, `sum by (subscription) (rate(authorized_calls[5m]))`, `(sum(limited_calls) / (sum(authorized_calls) + sum(limited_calls))) OR vector(0)`. Kratos's own queries (see ADR-014) add the `limitador_namespace` filter since `user`/`subscription` aren't available here:
```promql
sum(authorized_calls{limitador_namespace="llm/facebook-opt-125m-simulated-kserve-route"})
sum(authorized_hits{limitador_namespace="llm/facebook-opt-125m-simulated-kserve-route"})
```

**Why `authorized_hits` = tokens, not just another request counter**: this model has a Kuadrant `TokenRateLimitPolicy` (not a plain `RateLimitPolicy`) applied, confirmed `Enforced`. TokenRateLimitPolicy weights each "hit" by the request's actual token usage (parsed from the LLM response body) rather than counting 1 per request — confirmed by the live ~45:1 hits-to-calls ratio, a plausible tokens-per-request figure for this model, not a 1:1 ratio a plain request counter would show. The docs page confirms this is total (prompt+completion) tokens per request; prompt/completion split "requires upstream Kuadrant wasm-shim changes" (not currently available).

**A second, inconsistent dashboard format in the same repo**: `deployment/components/observability/observability/dashboards/usage-dashboard.yaml` (a Perses dashboard, distinct from the canonical Grafana one linked from the docs page) uses `authorized_calls_total`/`authorized_hits_total`/`limited_calls_total` (`_total` suffix) with `user`/`subscription`/`model`/`limitador_namespace` labels — neither the suffix nor the richer labels match what's live on this cluster or what the canonical docs describe. Worth knowing this file exists and disagrees, but don't treat it as authoritative over the docs page + a live series check.

## maas-api (control-plane traffic — NOT what Kratos uses for request/token validation)

Source: `maas-api/internal/metrics/prometheus.go` in the upstream repo (read literally). Tracks HTTP calls to maas-api's *own* endpoints (`/maas-api/v1/api-keys` etc. — key lifecycle), not inference traffic. Scraped via its own `metrics_service.yaml`.

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `maas_api_http_requests_total` | counter | `method`, `route`, `status`, `tenant_name` | HTTP requests served by maas-api |
| `maas_api_http_request_duration_seconds` | histogram | `method`, `route`, `status`, `tenant_name` | maas-api request latency |
| `maas_api_http_requests_in_flight` | gauge | `method` | Concurrent in-flight maas-api requests |
| `maas_api_key_validation_total` | counter | `tenant_name`, `result` | API key validation attempts (used by the AuthPolicy's `apiKeyValidation` metadata call) |
| `maas_api_token_mint_total` | counter | `tenant_name`, `result` | API key creation attempts |
| `maas_requests_total` | counter | none | Unlabeled total HTTP requests (kept low-cardinality by design, per a code comment) |
| `maas_request_duration_seconds` | histogram | none | Unlabeled request latency |
| `maas_request_rejections_total` | counter | `reason` (rate_limited / unauthorized / no_capacity / quota_exceeded) | Routing-level rejections |

maas-api has **no metrics endpoint documented in the official observability docs table** ("Pod status only") despite this package existing in source — the docs table appears to predate or not cover this internal instrumentation. Confirmed via the Kubernetes API-server pod-proxy technique above that the maas-controller pod (a different component, the CRD reconciler) only exposes standard `controller-runtime` operational metrics (`controller_runtime_reconcile_*`, `certwatcher_*`) — no business metrics.

## vLLM (per-model inference metrics — not currently usable for Kratos's default target model)

Exposed on `/metrics` port 8000. Supported backends per the docs: vLLM v0.7.x, llm-d v0.1.x, llm-d-inference-sim v0.8.2. Confirmed present (with real values) for models on this cluster that have a PodMonitor/ServiceMonitor — but **confirmed absent** for `facebook-opt-125m-simulated`, the only model MaaS currently exposes on this cluster, since it's a lightweight simulator, not one of those supported backends. Included here for completeness / future use if Kratos is ever pointed at a real vLLM-backed model.

| Metric | Type | Description |
|---|---|---|
| `vllm:num_requests_running` / `vllm:num_requests_waiting` | gauge | Requests currently processing / queued |
| `vllm:request_prompt_tokens` / `vllm:request_generation_tokens` | histogram | Per-request token counts (`_sum` suffix gives the cumulative total) |
| `vllm:prompt_tokens_total` / `vllm:generation_tokens_total` | counter | Total prompt/generation tokens processed (Python `prometheus_client` appends `_total`, unlike Limitador's metrics above) |
| `vllm:kv_cache_usage_perc` | gauge | KV-cache usage, 0-1 |
| `vllm:request_queue_time_seconds` | histogram | Time queued before processing (vLLM/llm-d only) |
| `vllm:request_success_total` | counter | Successful requests |
| `vllm:request_prefill_time_seconds` / `vllm:request_decode_time_seconds` | histogram | Prefill / decode phase time |

All labeled by `model_name`. Also confirmed present on other models on this cluster (broader set beyond the docs' table): `vllm:e2e_request_latency_seconds_*`, `vllm:time_to_first_token_seconds_*`, `vllm:inter_token_latency_seconds_*`, `vllm:prefix_cache_hits_total`/`queries_total`, `vllm:num_preemptions_total`, `vllm:spec_decode_num_accepted_tokens_total`/`draft_tokens_total`, `vllm:lora_requests_info`, `vllm:tool_call_parser_invocations_total`, and each counter's `_created` counterpart. Some (e.g. `request_queue_time_seconds`) are lazily registered and won't appear until the relevant event first happens — a dashboard panel showing "No Data" doesn't necessarily mean the metric doesn't exist.

For a real vLLM-backed model, total_tokens could alternatively be sourced as `sum(vllm:prompt_tokens_total{model_name="..."}) + sum(vllm:generation_tokens_total{model_name="..."})`.

## Istio gateway (not independently verified live this session)

`istio_request_duration_milliseconds_bucket`, labeled `destination_service_name` and `subscription` (intentionally *not* per-user, to bound cardinality). The `subscription` label isn't native to Istio — it's added via an Istio `Telemetry` CR that copies the `X-MaaS-Subscription` header (injected by the MaaS `AuthPolicy`) into a metric tag:
```yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: latency-per-subscription
spec:
  metrics:
  - overrides:
    - match: {metric: REQUEST_DURATION}
      tagOverrides: {subscription: {value: 'request.headers["x-maas-subscription"]'}}
```
Example: `histogram_quantile(0.99, sum by (subscription, le) (rate(istio_request_duration_milliseconds_bucket{subscription!=""}[5m])))` for P99 latency per subscription.

## Authorino (not independently verified live this session)

Exposed on `/server-metrics` port 8080 — note this is a **different** endpoint from the `authorino-operator-monitor` PodMonitor seen on-cluster (`kuadrant-system` namespace), which scrapes plain `/metrics` for generic controller-runtime metrics only. MaaS's own `authorino-server-metrics` ServiceMonitor is what scrapes `/server-metrics` for the auth-evaluation metrics below (the AuthPolicy CRs seen on-cluster have per-filter `metrics: true` flags enabling some of this, e.g. the `apiKeyValidation`/`subscription-info` evaluators).

| Metric | Type | Labels |
|---|---|---|
| `auth_server_authconfig_total` | counter | `namespace`, `authconfig` |
| `auth_server_authconfig_duration_seconds` | histogram | `namespace`, `authconfig` |
| `auth_server_authconfig_response_status` | counter | `namespace`, `authconfig`, `status` |
| `auth_server_response_status` | counter | `status` |
| `auth_server_evaluator_total` | counter | `namespace`, `authconfig`, `evaluator_type`, `evaluator_name` |
| `auth_server_evaluator_cancelled` | counter | same as above — evaluator failures/cancellations |

For MaaS-specific evaluators, filter `evaluator_type="METADATA_GENERIC_HTTP"` and `evaluator_name=~"apiKeyValidation|subscription-info"` — like everything else in this doc's Limitador section, these series only appear after traffic actually hits each evaluator.

If ever needed for Kratos, verify the above the same way Limitador was verified — a live `/api/v1/series` query against Thanos Querier, not just the docs — since the Limitador case in this doc showed real label availability can differ from what's documented even when the metric names match.

## Grafana dashboards (not deployed/verified this session)

Upstream ships two pre-built dashboards (`./scripts/observability/install-grafana-dashboards.sh`, needs a cluster-wide Grafana instance labeled `app=grafana`): a **Platform Admin** dashboard (component health, token/request/success-rate/latency summary, per-model and per-subscription traffic breakdown, top users, resource allocation) and an **AI Engineer** dashboard (a caller's own usage summary/trends). Manual-import JSON for a token-metrics-focused dashboard: [`maas-token-metrics-dashboard.json`](https://github.com/opendatahub-io/models-as-a-service/blob/main/docs/samples/dashboards/maas-token-metrics-dashboard.json). Neither was deployed on the researched cluster — Kratos doesn't depend on them, but they're the human-facing equivalent of what `MAAS_METRICS_QUERIES` queries programmatically.

## See also
- ADR-014 (`docs/architecture/adrs/ADR-014-maas-metrics-cross-validation.md`) for the actual decision, what Kratos wires up, and why.
- Upstream docs: [`opendatahub-io.github.io/models-as-a-service/latest/observability/metrics-and-dashboards/`](https://opendatahub-io.github.io/models-as-a-service/latest/observability/metrics-and-dashboards/) — the canonical source for this doc's Limitador/vLLM/Istio/Authorino/Grafana content; raw source read directly (`docs/content/observability/metrics-and-dashboards.md` in the repo) rather than relying on a summarized fetch of the rendered page, after an earlier summarized pass introduced a metric-naming inaccuracy this doc has since corrected.
