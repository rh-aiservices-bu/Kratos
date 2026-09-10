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
Both queries were verified live with real non-zero data, and the bare metric names (`authorized_calls`/`authorized_hits`, no suffix) match the canonical upstream docs exactly. See `docs/architecture/maas-metrics-reference.md` for the full catalog of every metric-emitting component found during this research (maas-api, vLLM, Istio, Authorino) — not just the two used here — including a noted label discrepancy: the docs describe `authorized_calls`/`authorized_hits` as carrying `user`/`subscription`/`model` labels, but this cluster's deployed Limitador only exports `limitador_namespace`. `limitador_namespace`'s exact value is a deployment-time constant tied to whichever model MaaS exposes (same spirit as `DEFAULT_MODEL`) — re-verify if the target model changes.

**Comparison method — baseline delta**: `ScenarioRunner.run()` takes one metrics snapshot immediately before task execution starts and stores it as `shared_state["metrics_baseline"]`. Each subsequent poll writes the raw current values to `shared_state["metrics"]` *and* a computed `{name}_delta = current - baseline` for every metric present in both. This is robust regardless of whether the underlying Prometheus counter is global/cumulative or scoped to a subscription/key that outlives a single run — the delta always reflects only what happened during this run.

**Drift handling — tolerance band + bounded settle-until-passing retry**: the match-assertion type accepts a `tolerance_pct`; comparisons pass if `abs(observed - expected) <= tolerance_pct/100 * max(abs(expected), 1)`. This alone isn't sufficient, though — a scenario that finishes faster than Prometheus's scrape interval reads back a stale value (not "close but outside tolerance") even though the traffic really happened, since Limitador's own counters are already correct by the time a task finishes — only Prometheus's next *scrape* of them is pending. Confirmed live: this cluster's `scrapeInterval` is 30 s cluster-wide.

`_settle_and_evaluate()` in `harness/runner.py` handles this directly: poll MaaS metrics every 5 s, re-evaluating the assertion(s) being checked after each poll, and stop as soon as **all of them are PASSING** — or give up at a `max_wait_s` cap (default 65 s, tunable per-assertion, see below) and report the last evaluation. This checks the one thing that actually matters (did the assertion pass) instead of inferring "is the data ready" from an indirect signal.

Four earlier attempts got this wrong, each in a different, increasingly subtle way:
1. **Stop on the first metrics value that differs from the run's original baseline.** False positive for a longer run: the background poller (running every 5 s throughout the task loop) has usually already captured a mid-run scrape by the time the check ran, so this returned immediately with a value reflecting only partial traffic (confirmed on a 2000-request run where the last background poll landed at ~1600/2000).
2. **Stop once two consecutive fetches return the same value** ("has it settled", replacing #1). Also a false positive, in the opposite direction: the first fetch inside the retry loop almost always lands within the same still-stale scrape window as whatever the background poller last saw, so "same value twice" usually just means "no new scrape yet" — this returned instantly, with zero wait, on a real run.
3. **Compare each sample's response-envelope timestamp** (`value: [<timestamp>, "<value>"]`'s first element) against when the check started, replacing #2. Also failed instantly. Confirmed live (bracketing a query with wall-clock reads before/after it) that this envelope timestamp is the query's *evaluation* time, not the sample's scrape time — it reads back as approximately "now" regardless of when the counter was actually last scraped.
4. **Use PromQL's `timestamp()` function**, which does return a sample's true last-scrape time — confirmed live (`timestamp(authorized_calls{...})` correctly lagged "now" by ~29s, matching the scrape interval) — as its *value*, distinct from the envelope. This genuinely fixed #3's problem on a bare metric selector, but the actually-configured queries are wrapped in `sum(...)`, and aggregation functions compute a brand-new instant vector at query-evaluation time — discarding the underlying series' real timestamp before `timestamp()` ever sees it. `timestamp(sum(authorized_calls{...}))` confirmed live to read back as ~0s lag, same failure as #3, one aggregation layer removed from where it was tested. Rewriting arbitrary user-configured PromQL to push `timestamp()` inside an aggregation isn't reliably possible without a PromQL parser.
5. **A separate, distinct bug found alongside #1-4**: all of the above only ever applied to the scenario's *top-level* `assertions:` block, evaluated once after cleanup. But `metrics_fill.yaml` (like other scenarios) attaches its MaaS match-assertions to the `send_requests` *task* instead (`assertions:` nested under that task, not the scenario). The per-task assertion check ran a single immediate evaluation with **no retry at all**, so it failed instantly regardless of what the post-cleanup logic did — the whole retry mechanism was unreachable for the actual scenario being tested. This is why `_settle_and_evaluate()` is shared by both the per-task check and the final top-level check, not just the latter.

Given four attempts at inferring readiness from Prometheus's own API all broke on a different subtlety, checking the assertion's actual PASS/FAIL outcome directly — rather than any proxy for "is new data probably in yet" — was chosen deliberately to end that pattern: there's no Prometheus-specific behavior left to get wrong.

**Assertion format extension**: scenario `assertions:` values (top-level or per-task) may now be either the existing string form (`"< 5"`, unchanged) or a new dict form for explicit two-metric comparisons:

```yaml
assertions:
  maas_requests_match:
    compare: metrics.total_requests_delta
    to: inference_results.total_requests
    tolerance_pct: 5
    max_wait_s: 65   # optional, default 65 — see harness/runner.py:_configured_max_wait_s
```
`max_wait_s` is scenario/cluster-tunable since scrape intervals and reliability vary; all match-form assertions in a scenario (top-level and per-task combined) share one settle-loop mechanism, so the largest `max_wait_s` configured across them is what's actually used for any single settle call.

`compare`/`to` are explicit `namespace.key` references (resolved via `_extract_namespaced`), sidestepping the namespace-collision problem entirely — the existing bare-name single-metric lookup (`_extract_metric`) is untouched and unaffected.

**Harness-side ground truth**: `send_requests` now captures `response.usage.total_tokens` from each successful inference call and accumulates it into `shared_state["inference_results"]["total_tokens_sent"]`, giving a token-count comparison target that didn't previously exist.

**A UI side-effect of settling being genuinely slower now**: once a task's per-task assertions can take up to `max_wait_s` to settle (attempt #5 above), `shared_state["task_progress"]` — which the UI's per-task progress bar reads — was still being popped (frozen into its DONE-chip snapshot) the instant `task.run()` returned, *before* settling started. Since the task isn't appended to `task_results` (and so isn't shown as DONE) until settling finishes, this left a real window — up to `max_wait_s` — where the UI showed the task as RUNNING but had no progress data left to render, so the bar vanished and only reappeared once settling finished and the chip flipped to DONE. Fixed by moving the pop to after settling completes, so the bar stays visible for the whole wait.

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
- The bounded settle retry adds real wall-clock time to a run whose traffic genuinely stopped exactly at a scrape boundary (worst case, up to `max_wait_s`) — accepted since the alternative is a false FAILING on a correct run, which is worse for a testing harness than a slower one.

**Neutral:**
- `deploy/rbac-monitoring.yaml` adds a `ClusterRoleBinding` (cluster-scoped, unlike the rest of the harness's namespaced RBAC) — the only cluster-scoped grant the harness needs beyond its namespace.
- Supersedes the metric-namespace table in ADR-004 and the assertion-format description in ADR-010, both updated alongside this ADR.
