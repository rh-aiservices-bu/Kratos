# MaaS/RHOAI Metrics Reference

Findings from live-cluster research (`oc` read-only calls + Thanos Querier queries against `cluster-rkmhx.rkmhx.sandbox1230.opentlc.com`, the cluster `deploy/configmap-global.yaml` targets) plus literal source from the upstream [`opendatahub-io/models-as-a-service`](https://github.com/opendatahub-io/models-as-a-service) repo. Catalogs every metric-emitting component found, not just the two Kratos currently uses (see ADR-014 for the decision and what's actually wired up).

## Access method

All of these are scraped into Prometheus and queried the same way: via **Thanos Querier**, not a direct Prometheus connection. OpenShift runs two separate Prometheus instances — the platform one (`openshift-monitoring`) and a user-workload one (`openshift-user-workload-monitoring`) — and workload metrics (Limitador, vLLM, etc.) are scraped by the *user-workload* instance specifically (confirmed via the `prometheus="openshift-user-workload-monitoring/user-workload"` label on live query results). Thanos Querier merges both into one read endpoint, which is the standard/supported way to query "any cluster metric" without needing to know which instance scraped it:

```
GET https://thanos-querier-openshift-monitoring.apps.<CLUSTER_DOMAIN>/api/v1/query?query=<promql>
Authorization: Bearer <token>
```

Requires the querying identity to be bound to the `cluster-monitoring-view` ClusterRole (`deploy/rbac-monitoring.yaml` binds the Kratos SA to it). Verified this route/RBAC pattern exists and works on the live cluster using a real bearer token.

One-off debugging technique also used during research (not what Kratos uses at runtime): the Kubernetes API server can proxy directly to a pod's or service's own metrics port without Thanos or a port-forward, which is useful for a component whose metrics haven't been scraped/labeled yet:
```
oc get --raw /api/v1/namespaces/<ns>/pods/<pod-name>:<port>/proxy/metrics
oc get --raw /api/v1/namespaces/<ns>/services/http:<service-name>:<port>/proxy/metrics
```
(Note: ad-hoc `oc port-forward` did not work reliably in the research sandbox environment used for this session — the API server proxy path above was the reliable alternative.)

## Limitador (gateway data-plane traffic — what Kratos uses)

Source of the request/token counts that actually matter for validating "what did MaaS's gateway do with the requests Kratos sent." Emitted by Limitador (Kuadrant's rate-limiter, in the request path via Istio/Envoy), scraped via the `kuadrant-limitador-monitor` PodMonitor in `kuadrant-system`.

Confirmed live on the target cluster (real values at time of research):
| Metric | Type | Meaning | Confirmed live value |
|---|---|---|---|
| `authorized_calls` | counter | Requests that passed rate-limit/auth checks — **total_requests** source | 51119 |
| `authorized_hits` | counter | Token-weighted hit count (see below) — **total_tokens** source | 2314256 |
| `limited_calls` | counter | Requests rejected for exceeding a rate limit (429s) | 8771 |
| `limitador_up` | gauge | Limitador liveness | 1 |
| `datastore_partitioned` | gauge | Limitador's backing datastore health | 0 |

Only label present on any of these on this deployment: `limitador_namespace` (e.g. `llm/facebook-opt-125m-simulated-kserve-route` — the model's HTTPRoute name). No `user`/`subscription`/`model`/`tier` labels, despite those appearing in upstream's sample dashboards (see "Version/config discrepancy" below).

**Why `authorized_hits` = tokens, not just another request counter**: this model has a Kuadrant `TokenRateLimitPolicy` (not a plain `RateLimitPolicy`) applied, confirmed `Enforced`. TokenRateLimitPolicy weights each "hit" by the request's actual token usage (parsed from the LLM response body) rather than counting 1 per request — confirmed by the live ~45:1 hits-to-calls ratio, a plausible tokens-per-request figure for this model, not a 1:1 ratio a plain request counter would show.

**Version/config discrepancy worth knowing about**: the upstream repo's shipped Perses dashboard (`deployment/components/observability/observability/dashboards/usage-dashboard.yaml`) assumes `authorized_calls_total` / `authorized_hits_total` / `limited_calls_total` (`_total` suffix) with `user`, `subscription`, `model`, `limitador_namespace` labels. The actually-deployed Limitador on the researched cluster exports the **no-suffix, `limitador_namespace`-only** form. Confirmed by direct series query — use what's actually live on your cluster, don't assume the upstream manifest's naming without checking. (A different, unrelated MaaS sandbox cluster checked briefly during this research, `caiprod.rhoai.rh-aiservices-bu.com`, had `authorized_calls` but no `authorized_hits` series at all — label/metric availability isn't guaranteed consistent across Limitador deployments/versions, so re-verify per cluster before wiring `MAAS_METRICS_QUERIES`.)

Sample real PromQL used by Kratos (see ADR-014):
```promql
sum(authorized_calls{limitador_namespace="llm/facebook-opt-125m-simulated-kserve-route"})
sum(authorized_hits{limitador_namespace="llm/facebook-opt-125m-simulated-kserve-route"})
```

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

Standard vLLM Prometheus metric set, confirmed present (with real values) for models on this cluster that have a PodMonitor/ServiceMonitor — but **confirmed absent** for `facebook-opt-125m-simulated`, the only model MaaS currently exposes on this cluster, since it's a lightweight simulator without a real vLLM engine. Included here for completeness / future use if Kratos is ever pointed at a real vLLM-backed model.

Confirmed present (on other, non-MaaS models on the same cluster): `vllm:request_success_total`, `vllm:prompt_tokens_total`, `vllm:generation_tokens_total`, `vllm:e2e_request_latency_seconds_{bucket,count,sum}`, `vllm:time_to_first_token_seconds_*`, `vllm:inter_token_latency_seconds_*`, `vllm:request_prompt_tokens_*`, `vllm:request_generation_tokens_*`, `vllm:num_requests_running`, `vllm:num_requests_waiting`, `vllm:kv_cache_usage_perc`, `vllm:prefix_cache_hits_total`/`queries_total`, `vllm:num_preemptions_total`, `vllm:spec_decode_num_accepted_tokens_total`/`draft_tokens_total`, `vllm:lora_requests_info`, `vllm:tool_call_parser_invocations_total`, and their corresponding `_created` counterparts. All labeled by `model_name`.

For a real vLLM-backed model, total_tokens could alternatively be sourced as `sum(vllm:prompt_tokens_total{model_name="..."}) + sum(vllm:generation_tokens_total{model_name="..."})`.

## Istio gateway and Authorino (listed from docs, not independently verified live)

Per the official ODH MaaS observability docs component table (not cross-checked with a live query during this research pass):
- **Istio Gateway** — `/stats/prometheus` — `istio_requests_total`, `istio_request_duration_milliseconds_bucket` (gateway-level request counts and latency histograms).
- **Authorino** — `/metrics`, `/server-metrics` — auth latency and success/deny rate (the AuthPolicy CRs seen on-cluster have per-filter `metrics: true` flags enabling some of this).

If ever needed, verify these the same way Limitador was verified here — a live `/api/v1/series` query against Thanos Querier, not just the docs — since the Limitador case above showed real metric names/labels can differ from what's documented.

## See also
- ADR-014 (`docs/architecture/adrs/ADR-014-maas-metrics-cross-validation.md`) for the actual decision, what Kratos wires up, and why.
- Upstream docs: `opendatahub-io.github.io/models-as-a-service/latest/observability/`
