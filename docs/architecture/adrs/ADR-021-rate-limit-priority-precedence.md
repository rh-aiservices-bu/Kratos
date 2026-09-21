# ADR-021: Rate-Limit Priority Precedence via Auto-Selection, Not Live Arbitration

## Status

Accepted

## Context

`docs/architecture/empirical-verification-checklist.md` flagged "when two subscriptions target the same model with different `priority`, the higher-priority one's limit actually wins" as an untested claim. Before designing a scenario for it, a live read of a real `TokenRateLimitPolicy` (`oc get tokenratelimitpolicies -A`) showed the actual mechanism is different from the naive framing of the checklist row:

```yaml
spec:
  limits:
    models-as-a-service-simulator-free-facebook-opt-125m-simulated-tokens:
      rates: [{limit: 100, window: 1m}]
      when:
        - predicate: auth.identity.selected_subscription_key == "models-as-a-service/simulator-free@llm/facebook-opt-125m-simulated" && ...
    models-as-a-service-simulator-premium-facebook-opt-125m-simulated-tokens:
      rates: [{limit: 100000, window: 1m}]
      when:
        - predicate: auth.identity.selected_subscription_key == "models-as-a-service/simulator-premium@llm/facebook-opt-125m-simulated" && ...
```

Each subscription gets its **own** named rate-limit entry, gated by a predicate on `auth.identity.selected_subscription_key`. There's no live contention between two limits for one request — `priority` is resolved once, earlier in the chain, when MaaS decides which subscription a caller's key gets bound to (`selected_subscription_key`). This matches what `harness/tasks/auth.py`'s existing comment on `provision_api_key` already said ("auto-selects whichever subscription the caller's identity resolves to (highest priority among eligible ones)") — but that comment was never itself verified against a real `TokenRateLimitPolicy`, and the checklist row was written as if priority were arbitrated per-request. It isn't.

This reframes the test entirely: verifying priority precedence means verifying **auto-selection's outcome**, not racing two live rate limits against each other.

## Decision

**New scenario** `scenarios/rate_limit_priority_precedence.yaml`: create two `MaaSSubscription`s targeting the same model, both owned by `system:authenticated` (required — auto-selection only considers subscriptions the caller is *actually* eligible for; a synthetic group name the caller doesn't belong to, like `access_denied_no_policy` uses, would never be a candidate), with priorities chosen well clear of the existing `100` default (`50` and `200`) so this doesn't interact with a concurrently-running `rate_limit_validation`. Then `provision_api_key` **without** pinning `subscription` — letting real auto-selection happen — and assert the response names the higher-priority subscription.

**Verification mechanism reused, not reinvented**: this is exactly the `subscription`-echo check ADR-019 already built, just checking against an *expected* value instead of a *requested* one. Added a new, independent `expect_subscription` param to `ProvisionApiKeyTask` (`harness/tasks/auth.py`) — deliberately separate from the existing `subscription` param, since that one *forces* the binding by including it in the request body, while `expect_subscription` never touches the request and only grades the outcome. Two new counters on `key_provision_checks`: `expected_subscription_checked_count`/`expected_subscription_match_count`.

**A real bug found and designed around before it shipped, not after**: the obvious approach — run `ApplyRateLimitSubscriptionTask` twice, once per subscription, via ADR-019's registry-alias trick — does not work here. That task's cleanup bookkeeping (`shared_state["subscription_name"]`, `["_sub_created"]`, `["original_subscription"]`) is stored under **fixed** keys, not namespaced per task instance (unlike `SendRequestsTask`, which rebuilds `inference_results` fresh each run and has a no-op cleanup — nothing to collide). Two instances in one scenario would have the second overwrite the first's state before either `cleanup()` runs, so the first subscription's original state would be lost and both cleanups would act on the *second* subscription's identity. A registry alias only changes the task-progress/UI key, not `shared_state` — it wouldn't have caught this.

**Fix**: extracted the get-or-create/patch and restore-or-delete logic out of `ApplyRateLimitSubscriptionTask` into two small module-level helpers (`_get_existing_subscription`/`_create_or_patch_subscription`/`_cleanup_subscription`, plus `_subscription_body`), verified to leave `ApplyRateLimitSubscriptionTask`'s own behavior, `shared_state` keys, and existing test suite completely unchanged. Added a new task, `ApplyPriorityTestSubscriptionsTask` (`apply_priority_test_subscriptions`), that creates a *list* of subscriptions from one params block and tracks them as a list (`shared_state["priority_test_subscriptions"]`), so each one's create-vs-patch/restore-vs-delete state travels independently and cleanup handles every entry correctly regardless of how many there are.

## Consequences

**Positive:**
- Closes the checklist row with the mechanism that actually matches live behavior, not the mechanism the row's original wording implied — avoiding building (and then having to explain away) a scenario that couldn't possibly have tested what it claimed to.
- The `_apply_subscription`/`_cleanup_subscription`-style helper extraction is reusable for any future task needing to manage multiple `MaaSSubscription`s at once.
- `expect_subscription` is generically useful beyond this one scenario — any future check needing "did auto-selection pick what I expected" (without forcing it) can reuse it.

**Negative:**
- Both temp subscriptions are owned by `system:authenticated`, so for the run's duration they're in the auto-selection pool for *any* caller on the cluster doing an unpinned key creation, not just the harness — the same class of transient shared-cluster side effect `rate_limit_validation.yaml` already accepts (its own default owner is also `system:authenticated`), just doubled. Mitigated, not eliminated, by reliable cleanup and by choosing priorities that avoid colliding with the existing `100` default.
- **Confirmed live** (`cluster-rkmhx.rkmhx.sandbox1230.opentlc.com`): `expected_subscription_match_count == 1` and `error_rate_pct == 0` both PASSING on the first real run — auto-selection did pick the higher-priority (`200`) subscription over the lower one (`50`) for the `system:authenticated` caller, confirming the eligibility assumption and the literal-highest-priority-wins behavior. Cleanup verified via `oc get maassubscriptions` afterward — neither temp subscription left behind. This run only happened after fixing a separate, more fundamental bug (see ADR-009's second Update) that would have made every CR-based task fail regardless of this ADR's own logic being correct.

**Neutral:**
- The Access-control checklist's "policy without quota" open question and the platform-config rows stay untouched by this ADR — see ADR-022 and the checklist doc for what else moved in the same round.
