# MaaS Domain Model Reference

Catalog of the MaaS *governance/setup* objects — subscriptions, models, access control, tenant config, and the Kuadrant/Limitador enforcement layer beneath them — as distinct from `maas-metrics-reference.md`'s catalog of what those objects *emit*. Backs the "MaaS Setup" overview in the UI (see ADR-017) and is meant as the reference to check when designing a new scenario against a given cluster.

Findings from live-cluster research (`oc get`/`-o yaml` as `kube:admin` against `cluster-rkmhx.rkmhx.sandbox1230.opentlc.com`, the cluster `deploy/configmap-global.yaml` targets) plus the following upstream sources:
- Red Hat docs (RHOAI 3.5): [Govern LLM access with Models-as-a-Service](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html/govern_llm_access_with_models-as-a-service/deploy-and-manage-models-as-a-service)
- Upstream docs: [opendatahub-io.github.io/models-as-a-service](https://opendatahub-io.github.io/models-as-a-service/latest/)
- Upstream repo (CRDs/controller source of truth): [github.com/opendatahub-io/models-as-a-service](https://github.com/opendatahub-io/models-as-a-service)

**Known discrepancy found during this research (tracked separately, not fixed here):** `harness/tasks/subscription.py` writes `MaaSSubscription.spec.rpsLimit`. The live CRD schema below (`spec.modelRefs[].tokenRateLimits[]`, `spec.owner`, `spec.priority`) has no `rpsLimit` field at all — `rate_limit_validation` is likely broken against current RHOAI MaaS versions.

**Implementation status in the UI** (each section below is marked; see ADR-017 for the backend/frontend design): **A (Subscriptions)**, **B (Models)**, and **C (Access Control)** are live in the "MaaS Setup" tab. **D–I are catalog-only so far** — read here to understand the domain, but not yet surfaced as their own UI tabs.

## A. Subscriptions — `MaaSSubscription` (`maas.opendatahub.io/v1alpha1`, namespaced) — ✅ in UI

Grants a set of groups/users **quota** (token rate limits) for a set of models. Does **not** by itself grant gateway access — see Access Control below.

| Field | Meaning |
|---|---|
| `metadata.name`/`.namespace` | Identity — namespace is the MaaS install's subscription namespace (`models-as-a-service` on the research cluster, not fixed across installs) |
| `metadata.annotations["openshift.io/display-name"]` / `["openshift.io/description"]` | Human-readable label shown in dashboards |
| `spec.priority` | Resolution order — when a user's groups map to multiple subscriptions for the same model, highest priority wins. Upstream's recommended scheme: prod=100, staging=50, dev=0 (default), sandbox=-10, using gaps of ~10 rather than 0/1000/10000 |
| `spec.owner.groups[].name` / `spec.owner.users[]` | Who this subscription is granted to |
| `spec.modelRefs[]` | Per model: `name`, `namespace`, `tokenRateLimits[]` (`limit`, `window`, e.g. `100`/`"1m"`) |
| `status.phase` | e.g. `Active` |
| `status.conditions[]` | `Ready`; **`SpecPriorityDuplicate`** — `True` means this subscription's priority collides with another one targeting the same model, a real misconfiguration to surface prominently, not just log |
| `status.modelRefStatuses[]` / `status.tokenRateLimitStatuses[]` | Per-model reconciliation health and the generated `TokenRateLimitPolicy` name |

Live example (research cluster, two subscriptions on the same model, deliberately different priorities):
```yaml
spec:
  modelRefs:
  - name: facebook-opt-125m-simulated
    namespace: llm
    tokenRateLimits:
    - {limit: 100, window: 1m}
  owner:
    groups: [{name: system:authenticated}]
    users: []
  priority: 10          # "simulator-free"; "simulator-premium" has priority 20, limit 100000
```

Cross-check: `GET /v1/models` (MaaS REST) returns a `subscriptions[]` array per model (`name`, `displayName`, `description`) — a thinner reverse-index of the same relationship, useful to confirm the REST view matches the CRD view.

## B. Models — ✅ in UI

Three sources, merged (see `api/maas_client.py:list_models`):

1. **`MaaSModelRef`** (`maas.opendatahub.io/v1alpha1`, lives in the model's own namespace, e.g. `llm`): `metadata.annotations` (display name/description), `spec.modelRef.{kind,name}` (`LLMInferenceService` today; external providers are a separate `ExternalModel` object, not a `modelRef.kind` value), `status.phase`, `status.endpoint`, `status.httpRouteName/Namespace`, `status.httpRouteGatewayName/Namespace`.
2. **`GET /v1/models`** (MaaS REST, works with an SA token or an API key): `id`, `url`, `ready`, `owned_by` (`"<namespace>/<MaaSModelRef name>"` — the join key back to (1)), `modelDetails.{displayName,description}`, `subscriptions[]`.
3. **`LLMInferenceService`** (`serving.kserve.io/v1alpha2`, only when `modelRef.kind == LLMInferenceService`): `spec.replicas`, container `resources.{requests,limits}` (cpu/mem/GPU), `spec.router.gateway.refs`, `status.conditions[]` (`GatewaysReady`, `HTTPRoutesReady`, `MainWorkloadReady`, `RouterReady`, `WorkloadsReady`, `PresetsCombined`), `status.url`/`status.addresses[]` (internal + external).

`ExternalModel` (`maas.opendatahub.io/v1alpha1`, tech preview) maps a client-facing model name to an external provider (OpenAI/Bedrock/Gemini-style), with request-translation-vs-passthrough mode. None deployed on the research cluster — schema not fully verified live; `api/maas_client.py` shapes these minimally and always keeps the raw CR available rather than guessing at fields.

Each shaped model also carries a `hosting: "internal" | "external"` field, computed once in `api/maas_client.py` (`"internal"` iff `modelRef.kind == LLMInferenceService`) rather than left for the UI to re-derive from `kind` — so "is this actually served by OpenShift AI, or routed out to a third party?" has one answer, not one per caller.

## C. Access Control — ✅ in UI

**Two layers, both required** (per upstream docs, confirmed): a `MaaSSubscription` grants **quota**; a `MaaSAuthPolicy` grants **gateway access**. A subscription with no matching auth policy means a user has quota but can't reach the gateway at all; an auth policy with no matching subscription means a user can reach the gateway but is rate-limited to zero by the cluster's own deny-by-default `TokenRateLimitPolicy` (see D below) — both are real, surfaceable misconfigurations, not just two objects to list side by side.

**`MaaSAuthPolicy`** (`maas.opendatahub.io/v1alpha1`, namespaced): `spec.modelRefs[]`, `spec.subjects.{groups[],users[]}`, `status.authPolicies[]` (per-model `ready`/`reason`), `status.phase`.

**OpenShift `Group`** (`user.openshift.io/v1`, cluster-scoped): `metadata.name`, `users[]` — resolves a subscription's/auth-policy's group references down to actual usernames. MaaS "assigns users to subscriptions based on OpenShift group membership"; a user in multiple groups gets the highest-priority subscription among them (upstream docs). Research cluster has one group (`rhods-admins`, empty membership) — the feature must not assume any groups exist.

## D. Rate-Limiting Enforcement (the layer beneath the CRDs above)

What the `MaaSSubscription`/`MaaSAuthPolicy` intent actually compiles down to. Useful when a scenario's rate-limit assertion behaves unexpectedly and the CRD-level view alone doesn't explain why.

**`TokenRateLimitPolicy`** (`kuadrant.io/v1alpha1`) — one auto-generated per model (targeting its `HTTPRoute`) plus one cluster-wide default on the `Gateway` itself:
```yaml
# per-model, one `limits` entry per subscription targeting this model
spec:
  limits:
    models-as-a-service-simulator-free-facebook-opt-125m-simulated-tokens:
      counters: [{expression: auth.identity.userid}]
      rates: [{limit: 100, window: 1m}]
      when: [{predicate: 'auth.identity.selected_subscription_key == "models-as-a-service/simulator-free@llm/facebook-opt-125m-simulated" && !request.path.endsWith("/v1/models")'}]
  targetRef: {group: gateway.networking.k8s.io, kind: HTTPRoute, name: facebook-opt-125m-simulated-kserve-route}
status:
  conditions: [{type: Accepted, status: "True"}, {type: Enforced, status: "True"}]
```
```yaml
# cluster-wide default-deny on the Gateway itself — confirmed live, name "gateway-default-deny"
spec:
  defaults:
    limits:
      deny-all-by-default:
        rates: [{limit: 0, window: 1m}]
        when: [{predicate: '!request.path.startsWith("/maas-api") && !request.path.startsWith("/v1/models")'}]
    strategy: atomic
  targetRef: {group: gateway.networking.k8s.io, kind: Gateway, name: maas-default-gateway}
```
This is *why* "auth policy without a subscription" fails closed rather than open: anything not matched by a subscription-scoped policy falls through to this 0-req/min default.

**`Limitador`** (`limitador.kuadrant.io/v1alpha1`, cluster-singleton, in `kuadrant-system`): `spec.limits[]` (`name`, `max_value`, `seconds`, `namespace`, `conditions`, `variables`) — the literal counter definitions Envoy/Limitador enforce; `status.service.{host,ports}`.

## E. Tenant / Platform Configuration

- **`Tenant`** (deprecated) / **`MaasTenantConfig`** (current): `spec.gatewayRef`, `spec.apiKeys.maxExpirationDays`, `spec.telemetry.{enabled, metrics.captureOrganization/User/Group/ModelUsage}`, `status.phase/conditions`. Live example: `default-tenant` in `models-as-a-service`, `gatewayRef: {name: maas-default-gateway, namespace: openshift-ingress}`, phase `Active`.
- **`AITenant`** (tech preview multi-tenancy): dedicated tenant namespace, gateway, OIDC config — not in use on the research cluster.
- **`DataScienceCluster`**: `spec.components.aigateway.modelsAsAService.managementState: Managed` confirms MaaS itself is enabled.
- **`OdhDashboardConfig`** (`redhat-ods-applications`): `spec.dashboardConfig.{modelAsService, vLLMDeploymentOnMaaS, genAiStudio, externalModels, observabilityDashboard}` — adjacent RHOAI dashboard feature flags. All `true` on the research cluster.

## F. Gateway / Networking

- **`Gateway`** `maas-default-gateway` (`gateway.networking.k8s.io`, in `openshift-ingress`): LB address, class, `Programmed` condition.
- **`HTTPRoute`** per model: name (`<model>-kserve-route` pattern), namespace, parent gateway.

## G. Live Usage

Not part of the setup/config view above, but the natural next thing an admin wants once they can see the setup — see `docs/architecture/maas-metrics-reference.md` for the full metrics catalog (Limitador `authorized_calls`/`authorized_hits`, maas-api control-plane counters, vLLM per-model metrics, Grafana dashboards).

## H. API Keys

`POST /maas-api/v1/api-keys/search` — **unverified**: whether this is scoped to the calling identity's own keys only, or returns every key cluster-wide when called with an elevated SA token, was not confirmed against a live multi-user cluster during this research. Any admin-facing "all API keys" view must verify this live and label its actual scope rather than assume "all keys."

## I. Access Resolution (derived, not raw data)

Given a candidate user/group set, which subscription wins by priority, and which models are actually reachable (subscription AND matching auth policy) — synthesized from A–C above rather than read directly from any one object. See the MaaS Setup UI design notes for where this fits (currently a client-side stretch feature; may become a harness-composable check later).
