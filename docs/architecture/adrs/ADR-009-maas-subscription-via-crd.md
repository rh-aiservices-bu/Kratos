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
