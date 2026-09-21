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
| OpenShift Group membership changes (adding/removing a user) propagate to gateway access promptly, not after a caching delay | Gap — **kept around, not excluded**, but genuinely hard under this harness's model | Confirmed live: the only real `Group` on this cluster (`rhods-admins`) is a live admin group, not something to touch for a test. More fundamentally, `Group.users` membership doesn't meaningfully apply to a ServiceAccount caller (the harness's only identity) — testing this would need a real user identity the harness can impersonate, which it doesn't have today. |

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
| `POST /maas-api/v1/api-keys/search` is scoped to the caller's own keys, not all keys cluster-wide under an elevated SA token | **Still Gap** — honestly out of reach with a single identity | The harness only has one identity (its own SA token) to call `/search` with, so it can prove keys we created are findable, never that a *different* caller's keys are excluded. Would need a second identity/token available to the harness to close for real. |

## Model / subscription CR status truthfulness

| Claim | Status | Covered by |
|---|---|---|
| `MaaSModelRef.status.phase` only reaches `Ready` when both a `MaaSSubscription` and a matching `MaaSAuthPolicy` cover it (the governance-pairing rule the Models tab relies on) | Partial — implied by existing UI logic, never flipped live end-to-end | none — `access_denied_no_policy` creates the subscription-only half but doesn't assert on `MaaSModelRef.status.phase` itself |
| For an `ExternalModel`, traffic actually routes through the configured `ExternalProvider` endpoint, not an internal route | Gap | none — also blocked on RHOAI 3.5's `ExternalModel`/`ExternalProvider` schema not yet being live-verified at all (see `maas-domain-reference.md`) |

## Networking

| Claim | Status | Covered by |
|---|---|---|
| A `Gateway` showing `Programmed: true` actually accepts traffic | **Verified** (the CR-truthfulness half) — every scenario that successfully sends inference through the MaaS gateway is already implicit evidence, but nothing had asserted the CR's own condition explicitly until now | `check_platform_health`'s `gateway_status.programmed`, asserted in `scenarios/platform_health_check.yaml` (ADR-022). Confirmed live: there are *two* Gateways in `openshift-ingress` (`maas-default-gateway` and an unrelated `data-science-gateway`) — don't assume a cluster has only one. |
| An `HTTPRoute`'s `ownerReferences`-derived model attribution (Networking tab) matches where traffic for that route actually lands | **Verified** (the ownership-metadata half) | `check_platform_health`'s `http_route_status.owner_ref_matches`, asserted in `scenarios/platform_health_check.yaml` (ADR-022) — found by label selector (`app.kubernetes.io/name=<model>`), not an assumed `<model>-kserve-route` name pattern |

## Platform config

| Claim | Status | Covered by |
|---|---|---|
| Toggling `DataScienceCluster`'s MaaS management state (Managed/Removed) actually gates MaaS API availability | Gap — **deliberately not attempted**, kept around for later rather than closed or excluded | Confirmed live this is `spec.components.kserve.modelsAsService.managementState` (RHOAI 3.5+ path) on this cluster. Toggling it for real would disable MaaS *cluster-wide* for every caller, not just Kratos's own test resources — a materially different risk class than anything else in this checklist, which only ever creates/deletes its own synthetic, namespaced resources. Needs an explicit decision (e.g. a genuinely disposable test cluster) before attempting, not just careful code. |
| `OdhDashboardConfig` feature flags actually gate the behavior they claim to | Gap — same reasoning as above, deliberately not attempted | Same cluster-wide blast radius concern; also, most of its flags (`disableModelCatalog`, `genAiStudio`, ...) gate RHOAI dashboard UI behavior Kratos has no way to observe from the harness side at all. |

## Metrics scoping

| Claim | Status | Covered by |
|---|---|---|
| MaaS-reported request/token counts (baseline-delta) match what the harness actually sent, within tolerance | **Verified** | `scenarios/metrics_fill.yaml` (ADR-014/ADR-015) |
| Isolation from other concurrent callers on the same model route | **Accepted limitation, not a gap** — no metric in the catalog carries a run-id/caller-id label; isolation is time-window-based only. Documented in ADR-014/ADR-015 and CLAUDE.md's "Scoping caveat" section. Would need a caller-scoped Prometheus label (if a deployed Limitador ever exposes one) to close for real. |

## How to use this doc

When picking up the next item: read the row's "Covered by" column and the linked ADR/scenario/task for context, don't start from scratch. If a row has an "Open question," resolve it against a live cluster before writing any code — this repo has a specific, documented history (ADR-009) of scenarios built against an assumed-but-unverified schema shipping silently broken.
