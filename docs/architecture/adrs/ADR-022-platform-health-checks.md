# ADR-022: Read-Only Platform Health Checks

## Status

Accepted

## Context

Three rows in `docs/architecture/empirical-verification-checklist.md` shared a pattern: a CR the MaaS Setup UI displays (`TokenRateLimitPolicy`, `Gateway`, `HTTPRoute`) reports a healthy-looking `status.conditions` entry or `ownerReferences` link, but nothing had ever asserted that these actually say what they claim to — as opposed to the UI just rendering whatever the CR happens to contain, healthy or not. Unlike the rate-limit/access-control work so far, none of these three need a write at all: the claim under test is entirely about the CR's own reported state, not about arranging a fixture to provoke some behavior. That makes them the cheapest possible checklist items to close — no RBAC to add (`deploy/rbac-maas-readonly.yaml` already grants `get/list/watch` on all three resource kinds to the same `kratos` ServiceAccount the harness runs under, ADR-001), no cleanup to write, no shared-cluster side effects.

A live read pass before writing any code caught one thing that would otherwise have been a silent bug: `oc get gateway -A` returns **two** Gateways in `openshift-ingress` on this cluster (`maas-default-gateway` and an unrelated `data-science-gateway`); an initial truncated read looked like a naming mismatch against what CLAUDE.md documents, resolved by reading the untruncated list rather than assuming either the docs or the first read was wrong. Confirmed the one MaaS's own `HTTPRoute`s actually reference (via `spec.parentRefs`) is `maas-default-gateway`, matching the docs.

## Decision

**New task** `CheckPlatformHealthTask` (new file `harness/tasks/platform_health.py`, registered `check_platform_health`), bundling three read-only checks — bundled, unlike the write-tasks elsewhere in this codebase, because none has side effects or independent cleanup to coordinate:

1. **`TokenRateLimitPolicy`** for the target model — found by **label selector** (`maas.opendatahub.io/model=<model_name>`, confirmed live on this cluster's `maas-trlp-facebook-opt-125m-simulated`), in the model's own namespace, not an assumed generated name. Reads `status.conditions`, stores `Accepted`/`Enforced` as 0/1 flags.
2. **The MaaS gateway** (`gateway_name`/`gateway_namespace` params, defaulting to the confirmed-live `maas-default-gateway`/`openshift-ingress`, overridable per-install) — reads its `Programmed` condition.
3. **The target model's `HTTPRoute`** — found by label selector (`app.kubernetes.io/name=<model_name>`, confirmed live), checks its `ownerReferences` actually names an `LLMInferenceService` matching the model.

All three default to 0/not-found rather than raising when the resource is missing, so an absent or misconfigured resource fails its assertion honestly (a real signal) instead of the run hanging on PENDING forever.

**New scenario** `scenarios/platform_health_check.yaml`, new category `"Platform Health"` (added to both `ui/src/components/ScenarioList.tsx`'s `CATEGORY_ORDER` and `harness/tests/test_scenarios.py`'s `_KNOWN_CATEGORIES`) — a single task, four assertions, `cleanup: automatic` as a true no-op since nothing was ever created. Explicitly scoped to internally-hosted (`LLMInferenceService`-backed) models; `ExternalModel`/`ExternalProvider` routing stays a separate, still-open checklist item (its own schema is flagged unverified on RHOAI 3.5 elsewhere in the docs).

## Consequences

**Positive:**
- Closes three checklist rows for the cost of one small, read-only, zero-RBAC-change task.
- Label-selector-based lookup (rather than an assumed name pattern) means this survives a MaaS controller renaming its generated `TokenRateLimitPolicy`/`HTTPRoute` objects, so long as the labels themselves stay stable — a narrower, more defensible assumption than a name string.
- Genuinely cheap to run repeatedly (no key provisioning, no traffic, no CR mutation) — could reasonably run on a much tighter interval than the write-based scenarios if that's ever wanted (e.g. a lightweight periodic health probe).

**Negative:**
- The label keys (`maas.opendatahub.io/model`, `app.kubernetes.io/name`) are confirmed only against this one cluster's one real model — re-verify against a live `/api/v1/... ` read (the same caution CLAUDE.md already gives for Limitador metric names) before trusting this on a different install, rather than assuming the labels are universal.
- "Gateway showing `Programmed: true`" and "HTTPRoute ownership is correct" are necessary, not sufficient, conditions for "traffic actually flows" — every load-testing scenario that successfully completes inference is already stronger evidence of that than this task alone provides. This task closes the narrower, honest claim ("the CR's own reported state is what it says it is"), not the broader one.
- **Confirmed live** (`cluster-rkmhx.rkmhx.sandbox1230.opentlc.com`): all four assertions (`rate_limit_policy_accepted`/`_enforced`, `gateway_programmed`, `http_route_owner_matches`) PASSING on the first real run, each reading back `1.0` — the label-selector lookups for `TokenRateLimitPolicy`/`HTTPRoute` and the `maas-default-gateway` default both worked as designed against real cluster objects, not just mocks.

**Neutral:**
- No RBAC changes — confirmed `deploy/rbac-maas-readonly.yaml` already covers everything this task reads.
