# Empirical MaaS Verification Checklist

Kratos has two surfaces that make *claims* about live MaaS cluster state: the
"MaaS Setup" UI (ADR-017, pure read-only CR inspection) and the scenario
runner's assertions (which mix genuine cross-checks with harness-side-only
numbers, see ADR-014/ADR-015). Neither surface is automatically correct just
because it reads a CR or computes a number — a CR's `status.conditions` can
say "Enforced" while the gateway does something else, and an assertion that
only checks the harness's own client-side math can go green even if the
cluster silently ignored the thing under test (this happened for real —
`rate_limit_validation` shipped for a while checking only its own throughput
arithmetic, never Limitador's actual counters).

This doc catalogs every such claim worth empirically verifying — checking
what actually happens at the gateway/CR/metrics level, not just what's
displayed or computed. Status values:

- **Verified** — an existing scenario/task cross-checks this against live
  cluster behavior (not just a mocked unit test).
- **Gap** — no scenario/task checks this at all; it's an assumption baked
  into a doc, a UI panel, or an unexamined success case.
- **Partial** — some coverage exists but doesn't close the actual question
  (e.g. a harness-side-only assertion that never touches the real signal).

## Next Up (prioritized)

Four items picked to implement next, in no particular order; design notes below (also cross-referenced from their rows further down). **Platform config's two rows are explicitly out of scope going forward** — they test RHOAI's `DataScienceCluster`/`OdhDashboardConfig`, not MaaS itself, and both carry cluster-wide blast radius on top of being the wrong layer to test here.

### 1. OpenShift Group membership propagation

**Key unlock, confirmed live** (`maas-domain-reference.md` Catalog D): Authorino's `AuthConfig` supports *two* mutually-exclusive authentication paths — API-key pattern match (the `sk-oai-*` keys Kratos exclusively uses today) **and OpenShift token review**. That second path means a raw Kubernetes bearer token can authenticate to the gateway directly, with identity resolved via standard TokenReview (the same mechanism that already makes the harness's own SA resolve to `system:authenticated` — see `harness/tasks/subscription.py`'s `_DEFAULT_OWNER_GROUPS` comment). This changes the design from "impossible without a real user login" to a concrete, buildable plan:

1. Create a throwaway **test-identity ServiceAccount** in the `kratos` namespace (e.g. `kratos-group-test-identity`) and mint its token via the Kubernetes **TokenRequest API** (`create` on the `serviceaccounts/token` subresource) — no OAuth login, no impersonation needed.
2. Create a throwaway OpenShift **`Group`** (`user.openshift.io/v1`, cluster-scoped), initially *without* the test SA's fully-qualified username (`system:serviceaccount:kratos:kratos-group-test-identity`) in `.users`.
3. Set up a `MaaSSubscription` + `MaaSAuthPolicy` pair owned by that group, targeting a test model.
4. Send inference using the test SA's **raw token directly** (the OpenShift-token-review auth path, no API key minted at all) — expect denied.
5. Patch the Group to add the test SA's username to `.users`, retry — expect allowed, within some bound. *This bound is itself the thing under test*, so poll-with-max-wait (reusing the existing `_settle_and_evaluate`-style pattern) rather than assuming a fixed delay either way.
6. Remove from `.users`, retry — expect denied again, within some bound.
7. Cleanup: delete the Group, the test SA, and its associated CRs.

**Open question to verify live before assuming**: does `Group.users` accept a ServiceAccount's fully-qualified username string (`system:serviceaccount:<ns>:<name>`), or only real OpenShift user identities? This is the load-bearing assumption of the whole design — confirm it directly (e.g. patch a test Group with a made-up SA username and check whether a TokenReview-based request from that SA actually resolves as a member) before building the full scenario around it.

**New RBAC required, and why it needs the capability-gating below**: `create`/`get`/`patch`/`delete` on `groups.user.openshift.io` (cluster-scoped — creating/mutating an OpenShift Group is a meaningfully more sensitive grant than anything else Kratos has asked for so far, on par with or beyond the `secrets get` grant ADR-017 already flagged as its most sensitive); `create`/`delete` on `serviceaccounts` and `create` on `serviceaccounts/token` in the `kratos` namespace (minting arbitrary SA tokens, even scoped to SAs Kratos itself creates, is also a real elevated capability).

**UI/scenario requirement (yours, not optional)**: rather than this one scenario failing opaquely when the SA lacks these grants, build a **generalizable capability-gating mechanism**: an optional `requires_permissions:` list in scenario YAML (`{group, resource, verb}` tuples), checked via a `SelfSubjectAccessReview` per entry (same idea as `oc auth can-i`, using `AuthorizationV1Api`) — surfaced by `GET /api/scenarios` as `available`/`unavailable_reason` per scenario, same shape as the existing `bool | None` "couldn't tell" convention. `ScenarioList.tsx` grays out the card and disables Run with a tooltip explaining the missing RBAC, mirroring `MaasUnavailableNotice.tsx`'s existing style. Generalizes beyond this one scenario — any future elevated-permission scenario gets the same graceful degradation for free.

### 2. `POST /maas-api/v1/api-keys/search` scoped to caller only

The same TokenRequest trick above unlocks this too, and cheaply reuses infrastructure if item 1 is built first: mint **two** distinct test-identity ServiceAccount tokens (identity A, identity B), each bound to its own subscription/key. Identity A creates a key with a unique `name_prefix`. Identity B calls `/search` (using *its own* token, not identity A's or the harness SA's) with identity A's prefix and asserts the result is empty (or, if the finding is that scoping doesn't actually work, asserts it's non-empty — either way the claim gets a real answer instead of "unknown"). Requires `provision_api_key`/`verify_api_key_search` to accept an optional `token` override — the same pattern `send_requests` already established for `url`/`token` (ADR-012), not a new concept.

### 3. Tenant testing

See the new "Tenant testing" section below — brainstormed candidates, since this wasn't a checklist area before now.

### 4. `ExternalModel`/`ExternalProvider` routing

Blocked on two unresolved things, in order: (a) the RHOAI 3.5+ schema for these has never been confirmed against a live instance (`maas-domain-reference.md` Catalog B — "no `ExternalModel` was deployed on the research cluster even pre-upgrade") — first step is a pure read-only spike, `oc get externalmodels.inference.opendatahub.io -A` / `externalproviders...` on the now-upgraded cluster, to confirm or correct the assumed shape before writing anything; (b) testing real routing needs *something* to route to. Real third-party providers (OpenAI/Bedrock/Gemini) mean external network egress and third-party credentials/billing — a materially different dependency than anything else in this checklist. **Cheaper alternative worth designing around**: point a test `ExternalProvider` at an endpoint *Kratos itself controls or a cheap public echo endpoint* rather than a real provider, and confirm — by inspecting what actually comes back — that traffic really left through the external path rather than silently hitting an internal route. Would need a new CR-write task (`apply_external_model` or similar) and new write RBAC on `inference.opendatahub.io` (currently read-only).

## Tenant testing (brainstormed, not yet scoped)

Not a checklist area before this round — added per the "Tenant testing" request. `MaasTenantConfig`'s real schema (`maas-domain-reference.md` Catalog E, confirmed live): `spec.gatewayRef`, `spec.apiKeys.maxExpirationDays`, `spec.telemetry.{enabled, metrics.captureOrganization/User/Group/ModelUsage}`, `status.phase/conditions`. Candidate checks, roughly ordered by how buildable they look:

- **Tenant health truthfulness**: does `MaasTenantConfig.status.phase == "Active"`/`Ready` actually correlate with `/maas-api/v1/...` being reachable? Cheapest option here — read-only, same spirit as `check_platform_health` (ADR-022), could likely extend that same task rather than write a new one.
- **`gatewayRef` correctness**: does the tenant's declared `spec.gatewayRef` (`{name: maas-default-gateway, namespace: openshift-ingress}`) actually match the Gateway real traffic flows through? Another read-only cross-check, same low-risk shape as the two above.
- **Telemetry capture flags**: does `spec.telemetry.metrics.captureUser`/`captureGroup`/`captureModelUsage` actually gate whether per-user/group/model-labeled metrics show up (vs. aggregate-only)? Interesting and MaaS-specific (not a DSC/dashboard flag), but needs figuring out *where* such labeled metrics would even surface — worth a read-only live spike (`/api/v1/series` with a user/group label filter) before designing a scenario, same discipline as everything else in this doc.
- **`maxExpirationDays` enforcement**: closes the still-open API-key-lifecycle row above, but needs a cluster where this is actually configured (this one's `spec.apiKeys` is empty) — or accept mutating the tenant's own config for the duration of a test, which is a shared, tenant-wide mutation (lower blast radius than toggling `DataScienceCluster`, since it doesn't turn MaaS off, but still affects every caller's key-minting during the test window, not just Kratos's own synthetic resources) and deserves the same explicit go/no-go as anything else that touches shared state, not silent inclusion in a scenario.
- **Multi-tenant isolation**: does a subscription/model registered under one tenant stay invisible to a caller only eligible under another? Only testable with more than one real tenant present — this cluster has exactly one (`default-tenant`); `AITenant` (tech-preview multi-tenancy) isn't in use here. Flag as untestable on this cluster rather than force it.
- **Tenant deletion/recreation resilience**: excluded, same reasoning as `DataScienceCluster` toggling — deleting/recreating `MaasTenantConfig` risks tearing down `maas-api` for the whole tenant, not a synthetic resource Kratos owns.

## Rate-limit enforcement

| Claim | Status | Covered by |
|---|---|---|
| A `MaaSSubscription`'s configured `tokenRateLimits` limit actually causes Limitador to deny requests once exceeded | **Verified** | `scenarios/rate_limit_validation.yaml`'s `maas_denied_by_rate_limit` assertion (baseline-delta on Limitador's `limited_calls`) |
| The auto-generated `TokenRateLimitPolicy`'s `Accepted`/`Enforced` UI status (Rate Limiting tab) matches real enforcement, not just a healthy-looking condition | **Verified** | `check_platform_health` task, asserted in `scenarios/platform_health_check.yaml` (ADR-022) — reads `status.conditions` by label selector, not an assumed generated name |
| When two subscriptions target the same model with different `priority`, the higher-priority one's limit actually wins at the gateway | **Verified** — confirmed live that this is actually an auto-selection question, not a per-request race (see ADR-021) | `scenarios/rate_limit_priority_precedence.yaml`: two temp subscriptions, `provision_api_key`'s `expected_subscription_match_count` (no `subscription` pinned) |

## Access-control enforcement

| Claim | Status | Covered by |
|---|---|---|
| A group with quota (`MaaSSubscription`) but no matching `MaaSAuthPolicy` is denied at the gateway (`gateway-default-deny` fails closed) | **Verified** | `scenarios/access_denied_no_policy.yaml` |
| A group with a matching `MaaSAuthPolicy` but no `MaaSSubscription` covering the target model is rejected for lack of quota | Gap — **needs a live-cluster spike first** | See "Open question" below; not designed yet because it's unconfirmed whether a MaaS API key can even be minted without a `subscription` binding |
| The Access Simulator's `reachable` prediction (client-side derivation over `/api/maas/{models,subscriptions,auth-policies}`) matches what a real request with that identity actually gets | Gap — **deliberately deferred**, not attempted this round | `access_denied_no_policy` indirectly supports the "no policy → not reachable" half; nothing checks the simulator's UI output itself against a live call. Would need the harness to call Kratos's own API server over the network (a new harness→API-server dependency, a first for this codebase) — worth its own focused round rather than folding into an unrelated batch of work. |
| OpenShift Group membership changes (adding/removing a user) propagate to gateway access promptly, not after a caching delay | Gap — **next up, design in "Next Up" §1 above** | A concrete design now exists (mint a throwaway ServiceAccount via TokenRequest, use its raw token directly via Authorino's OpenShift-token-review auth path — no impersonation or real user login needed) — needs new, meaningfully elevated RBAC (Group + ServiceAccount-token creation) and a capability-gating mechanism so scenarios needing it degrade gracefully without that RBAC, see §1. |

**Open question for the "policy without quota" case**: `harness/tasks/auth.py`'s `provision_api_key` always passes an explicit `subscription` in the request body when one is configured, but it's never been confirmed whether the MaaS API can mint a key with *no* subscription at all (and if so, what identity/group that key presents at the gateway). Before designing a scenario for this, manually try `provision_api_key` with `subscription` omitted against a group that has a policy but no subscription, and observe what actually happens — don't assume, per the lesson in ADR-009 (three compounding bugs came from trusting an undocumented schema instead of checking live).

## API key lifecycle

All rows here are REST-only — no Kubernetes CR read or write, by design (ADR-019), since this is the section of the checklist that's actually achievable that way. `scenarios/api_key_lifecycle.yaml` is the first Kratos scenario with zero CR dependency at all.

| Claim | Status | Covered by |
|---|---|---|
| `provision_api_key`'s requested `subscription` binding actually took — the response's `subscription` field equals what was sent, not a silent auto-selected fallback | **Verified** | `harness/tasks/auth.py`'s `key_provision_checks.subscription_echo_match_count`, asserted in `scenarios/rate_limit_validation.yaml` and `scenarios/access_denied_no_policy.yaml` (the two scenarios that actually pass `subscription`) |
| The response's `name` field matches what was requested, with no silent truncation/sanitization | **Verified** | `key_provision_checks.name_echo_match_count`, asserted in `scenarios/api_key_lifecycle.yaml` |
| `expiresAt` is present at all on every created key | **Verified** (the CR-free half only) | `key_provision_checks.expires_at_present_count`, asserted in `scenarios/api_key_lifecycle.yaml` |
| `expiresAt`'s actual value is consistent with the tenant's configured `MaasTenantConfig.spec.apiKeys.maxExpirationDays` | Gap (unchanged) | Needs reading `MaasTenantConfig`, a CR — deliberately not pulled into `api_key_lifecycle.yaml` to keep that scenario CR-free. Confirmed live: this cluster's `MaasTenantConfig.spec` is **empty** — nothing is even configured to compare against right now, independent of whatever schema question a CR-based check would also need to resolve. |
| Revocation (`DELETE /maas-api/v1/api-keys/{id}`) takes effect immediately for inference, not after a caching delay somewhere in the auth chain | **Verified** | `scenarios/api_key_lifecycle.yaml`: `revoke_api_keys` then `verify_revoked_key_denied` (a registry alias of `send_requests`) asserts `unauthorized_count > 0` on the very next request |
| `POST /maas-api/v1/api-keys/search` finds the keys this run created, filtered correctly by `name_prefix` | **Verified** (inclusion + filtering only) | `verify_api_key_search` task, asserted in `scenarios/api_key_lifecycle.yaml` |
| `POST /maas-api/v1/api-keys/search` is scoped to the caller's own keys, not all keys cluster-wide under an elevated SA token | Gap — **next up, design in "Next Up" §2 above** | No longer genuinely out of reach: the TokenRequest-minted second identity from §1 unlocks this too — two distinct SA tokens, each searching for the other's keys. Needs `provision_api_key`/`verify_api_key_search` to accept an optional `token` override, same pattern `send_requests` already has for `url`/`token` (ADR-012). |

## Model / subscription CR status truthfulness

| Claim | Status | Covered by |
|---|---|---|
| `MaaSModelRef.status.phase` only reaches `Ready` when both a `MaaSSubscription` and a matching `MaaSAuthPolicy` cover it (the governance-pairing rule the Models tab relies on) | Partial — implied by existing UI logic, never flipped live end-to-end | none — `access_denied_no_policy` creates the subscription-only half but doesn't assert on `MaaSModelRef.status.phase` itself |
| For an `ExternalModel`, traffic actually routes through the configured `ExternalProvider` endpoint, not an internal route | Gap — **next up, design in "Next Up" §4 above** | Blocked on a read-only schema-confirmation spike first (no `ExternalModel` existed on this cluster as of last check), then a CR-write task pointed at an endpoint Kratos controls rather than a real third-party provider, to avoid needing external credentials/billing. |

## Networking

| Claim | Status | Covered by |
|---|---|---|
| A `Gateway` showing `Programmed: true` actually accepts traffic | **Verified** (the CR-truthfulness half) — every scenario that successfully sends inference through the MaaS gateway is already implicit evidence, but nothing had asserted the CR's own condition explicitly until now | `check_platform_health`'s `gateway_status.programmed`, asserted in `scenarios/platform_health_check.yaml` (ADR-022). Confirmed live: there are *two* Gateways in `openshift-ingress` (`maas-default-gateway` and an unrelated `data-science-gateway`) — don't assume a cluster has only one. |
| An `HTTPRoute`'s `ownerReferences`-derived model attribution (Networking tab) matches where traffic for that route actually lands | **Verified** (the ownership-metadata half) | `check_platform_health`'s `http_route_status.owner_ref_matches`, asserted in `scenarios/platform_health_check.yaml` (ADR-022) — found by label selector (`app.kubernetes.io/name=<model>`), not an assumed `<model>-kserve-route` name pattern |

## Platform config

**Out of scope going forward** (not just deferred) — both rows below test RHOAI's `DataScienceCluster`/`OdhDashboardConfig`, the platform layer MaaS happens to run on top of, not MaaS itself. Kept in this doc for completeness/history, not as backlog.

| Claim | Status | Covered by |
|---|---|---|
| Toggling `DataScienceCluster`'s MaaS management state (Managed/Removed) actually gates MaaS API availability | Gap — **out of scope**: wrong layer (RHOAI DSC, not MaaS) *and* cluster-wide blast radius | Confirmed live this is `spec.components.kserve.modelsAsService.managementState` (RHOAI 3.5+ path) on this cluster. Toggling it for real would disable MaaS *cluster-wide* for every caller, not just Kratos's own test resources. |
| `OdhDashboardConfig` feature flags actually gate the behavior they claim to | Gap — **out of scope**, same reasoning | Same cluster-wide blast radius concern; also, most of its flags (`disableModelCatalog`, `genAiStudio`, ...) gate RHOAI dashboard UI behavior Kratos has no way to observe from the harness side at all. |

## Metrics scoping

| Claim | Status | Covered by |
|---|---|---|
| MaaS-reported request/token counts (baseline-delta) match what the harness actually sent, within tolerance | **Verified** | `scenarios/metrics_fill.yaml` (ADR-014/ADR-015) |
| Isolation from other concurrent callers on the same model route | **Accepted limitation, not a gap** — no metric in the catalog carries a run-id/caller-id label; isolation is time-window-based only. Documented in ADR-014/ADR-015 and CLAUDE.md's "Scoping caveat" section. Would need a caller-scoped Prometheus label (if a deployed Limitador ever exposes one) to close for real. |

## How to use this doc

When picking up the next item: read the row's "Covered by" column and the linked ADR/scenario/task for context, don't start from scratch. If a row has an "Open question," resolve it against a live cluster before writing any code — this repo has a specific, documented history (ADR-009) of scenarios built against an assumed-but-unverified schema shipping silently broken.

The "Next Up" section's four items were prioritized together because #1 and #2 share the same new mechanism (a TokenRequest-minted throwaway ServiceAccount identity) — building #1 first makes #2 nearly free. Before writing any code for #1, confirm the one load-bearing assumption flagged there (`Group.users` accepting a ServiceAccount's fully-qualified username) live, and build the `requires_permissions:` capability-gating mechanism alongside it rather than after — it's meant to be generalizable to future elevated-permission scenarios too, not a one-off for this scenario.
