# ADR-009: MaaSSubscription Rate Limits via Kubernetes CRD

## Status

Accepted

## Context

The `rate_limit_validation` scenario needs to configure a rate limit on a MaaS subscription, fire a burst of requests, and then assert that observed throughput stayed at or below the configured limit.

The MaaS REST API (`/maas-api/v1/...`) provides endpoints for API key lifecycle operations only. There is no REST endpoint for creating or modifying subscriptions or their rate limits.

Options considered:

1. **REST API**: not available. Ruled out.
2. **`oc` / `kubectl` CLI inside the Job pod**: shelling out to `kubectl apply` works but introduces a dependency on the binary being present in the image and is harder to test.
3. **`kubernetes.client.CustomObjectsApi`**: the Kubernetes Python client (already a dependency) can create and patch arbitrary Custom Resources, including `MaaSSubscription` objects from the `maas.opendatahub.io/v1alpha1` API group.

## Decision

Manage `MaaSSubscription` CRs using **`kubernetes.client.CustomObjectsApi`** in the `apply_rate_limit_subscription` task (`harness/tasks/subscription.py`). The task creates or patches the CR with the desired `rps_limit`, stores the original CR state in `shared_state["original_subscription"]`, and its `cleanup()` restores or deletes the CR.

Group/version/kind:
- `group`: `maas.opendatahub.io`
- `version`: `v1alpha1`
- `plural`: `maassubscriptions`

## Consequences

**Positive:**
- No extra binary dependencies in the image; `kubernetes` client is already required for Job management.
- Full programmatic control: create, patch, get, and delete operations are all available.
- Cleanup can precisely restore the original state rather than simply deleting the CR (in case the subscription pre-existed).
- Consistent with how the rest of the harness interacts with the cluster (Kubernetes Python client throughout).

**Negative:**
- The `MaaSSubscription` CRD schema is not yet fully documented; the task implementation will need to be updated if the schema changes between RHOAI versions.
- The SA must have `get`, `create`, `patch`, `delete` on `maassubscriptions` in the appropriate namespace. This must be added to `rbac.yaml`.

**Neutral:**
- This is the only task that manages a Kubernetes CR directly; all other Kubernetes interactions are limited to Jobs and Pods.
- The MaaS REST API remains the correct path for API key lifecycle; this decision does not affect that layer.

## Update: schema, namespace, and RBAC corrections

The "Negative" consequence above was exactly right to flag: live-cluster research (see `docs/architecture/maas-domain-reference.md` Catalog item A, and ADR-017) found the real `MaaSSubscription` schema has no `spec.rpsLimit` at all. Three separate, compounding bugs were found and fixed together, since fixing only one would have left the scenario silently broken:

1. **Wrong schema.** The real shape is `spec.priority` (int), `spec.owner.{groups[].name, users[]}`, `spec.modelRefs[].tokenRateLimits[].{limit, window}` — rate limits are per-model, in tokens per time window, not a flat `rpsLimit`. `harness/tasks/subscription.py` now builds this shape and requires `model_name`/`model_namespace` params (previously only `subscription_name`/`namespace`, since the old schema had no per-model concept at all).

2. **Wrong namespace, silently.** `deploy/rbac.yaml`'s original grant was a namespaced `Role` bound only to the `kratos` namespace, and the task's default (`ctx.config.get("NAMESPACE", "default")`, i.e. `NAMESPACE=kratos` from the global ConfigMap) created the CR *in the kratos namespace*. A `MaaSSubscription` only gets reconciled by the MaaS controller when it lives in the install's actual tenant namespace (e.g. `models-as-a-service`) — a CR in `kratos` is accepted by the API server (CRDs are cluster-wide resource *types*; any namespace is syntactically valid) but the controller never looks at it there. This means `rate_limit_validation` had never actually exercised real rate-limit enforcement, regardless of the schema bug — it created an inert object every time. Fixed by moving this grant to a new cluster-scoped `deploy/rbac-maas-subscription-write.yaml` (`ClusterRole`/`ClusterRoleBinding`, same reasoning as `rbac-maas-readonly.yaml`: the tenant namespace is install-specific, not fixed) and making `namespace` a required scenario config value (`subscription_namespace`) instead of silently defaulting to the harness's own namespace.

3. **No guarantee the test's own keys would use this subscription.** Even with (1) and (2) fixed, `provision_api_key`'s created keys resolve to *whichever* subscription the caller's identity is eligible for (highest priority among matches) unless told otherwise — with other subscriptions potentially present on the cluster (e.g. the sample `simulator-free`/`simulator-premium`), there was no guarantee the harness's own test keys would land on the CR this scenario just created and is trying to validate. Fixed by giving `provision_api_key` an optional `subscription` param, passed through to `POST /maas-api/v1/api-keys`'s `subscription` field (confirmed in the community guide's request shape), and wiring `rate_limit_validation.yaml` to pass the same `${config.subscription_name}` to both tasks.

**Consequence of (1): the assertion changed meaning, not just its field name.** Kuadrant's `TokenRateLimitPolicy` (what a `MaaSSubscription` compiles down to, see ADR-017 Catalog item D) counts *tokens* per window, not requests — there is no way to configure a literal requests-per-second limit via this CRD. The old scenario's `throughput_rps <= rate_limit_rps` assertion was checking a dimension the CRD can't actually enforce. Fixed honestly rather than patched around: `harness/tasks/inference.py` gained a `token_throughput_per_sec` metric (mirroring the existing `throughput_rps` computation, same `elapsed` denominator), and the task defaults the CR's `tokenRateLimits[].window` to `"1s"` specifically so the configured `token_limit` is directly comparable, unit-for-unit, to that new metric with no conversion — `rate_limit_validation.yaml`'s assertion is now `token_throughput_per_sec <= token_limit`. Anyone overriding `token_window` to something other than `"1s"` needs to adjust what they compare `token_limit` against themselves; this isn't done automatically.

**Not yet verified against a real cluster** — this fix was written against the documented/researched schema (confirmed live for read purposes throughout ADR-017's work) but the corrected write path itself has only been exercised by mocked unit tests (`harness/tests/test_subscription.py`), not a live `rate_limit_validation` run. Verify end-to-end before relying on this scenario's pass/fail result.
