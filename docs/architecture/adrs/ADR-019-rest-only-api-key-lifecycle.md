# ADR-019: REST-Only API Key Lifecycle Validation

## Status

Accepted

## Context

Every empirical-verification scenario built so far (ADR-014, ADR-015, ADR-018) that checks something beyond the harness's own client-side math does it by reading or writing a Kubernetes Custom Resource directly via `kubernetes.client.CustomObjectsApi` — `MaaSSubscription`, `MaaSAuthPolicy`, `Limitador`. CRs are exactly the layer most likely to change shape across MaaS/RHOAI upgrades: ADR-009's "three compounding bugs" happened because `MaaSSubscription`'s real schema wasn't what was assumed from docs. Every CR-dependent scenario built since carries that same maintenance risk.

A pass over `docs/architecture/empirical-verification-checklist.md`, row by row, asking "could this be checked through the MaaS REST API instead of a CR?" found that most rows genuinely can't — arranging the *fixture* for a rate-limit or access-control test requires creating a `MaaSSubscription`/`MaaSAuthPolicy`, there's no REST equivalent. But the entire **API key lifecycle** section can be closed purely through `/maas-api/v1/api-keys*`, since `provision_api_key` (`harness/tasks/auth.py`) already lives there and reads only `id`/`key` from a much richer create response.

## Decision

**Extend `ProvisionApiKeyTask`** to capture the full create response (`name`, `subscription`, `expiresAt`, not just `id`/`key`) and self-check it against what was requested, writing plain-numeric counters into `shared_state["key_provision_checks"]` (`total_keys`, `name_echo_match_count`, `subscription_checked_count`/`subscription_echo_match_count`, `expires_at_present_count`). All-numeric by design — `harness/result.py`'s assertion evaluator only compares floats, so a task-computed count/flag is how every check in this codebase becomes assertable, not a change to the evaluator itself. `subscription_echo_match_count` piggybacks onto `rate_limit_validation.yaml`/`access_denied_no_policy.yaml` (which already pass `subscription` for their own reasons) at zero added CR-coupling, closing ADR-009 bug #3's still-open verification hole.

**Two new tasks, same file** (`harness/tasks/auth.py`):
- `RevokeApiKeysTask` (`revoke_api_keys`) — revokes the current key pool *mid-scenario*, not at cleanup time, so a later task can confirm denial is immediate. Shares a `_revoke_keys(ctx)` helper extracted from `ProvisionApiKeyTask.cleanup()`'s existing DELETE loop (refactor, not new behavior) — the scenario's own final cleanup then harmlessly re-attempts DELETE on already-gone keys, swallowed and logged like any other cleanup failure, not a new failure mode.
- `VerifyApiKeySearchTask` (`verify_api_key_search`) — POSTs to `/maas-api/v1/api-keys/search` with a `name_prefix`, compares `len(items)` to how many keys this run created. **Honest scope limit**: with only the harness's own SA identity, this proves inclusion and prefix-filtering, not true caller-scoping (that a *different* caller's keys are excluded) — the checklist keeps that half flagged as Gap rather than claiming more than what's tested.

**Reusing `send_requests` under a second registry name, not a new class.** Confirming "the revoked key pool is denied" needs exactly `send_requests`'s existing logic, but giving a scenario's YAML task list two entries both named `send_requests` would collide: `harness/runner.py:_write_progress` builds each task's progress-JSON entry keyed by task name (`task_completed_progress`, a plain dict), and `ui/src/components/TaskProgress.tsx` uses `task.name` as the React list key for its pipeline chips. Two same-named tasks would step on each other's progress state and produce a duplicate-key warning/misrender in the UI. Fixed with a one-line registry alias in `harness/tasks/inference.py`: `REGISTRY["verify_revoked_key_denied"] = SendRequestsTask` — identical class, distinct scenario-facing name, distinct UI chip, no collision.

**New scenario** `scenarios/api_key_lifecycle.yaml` — the first MaaS:PAL scenario with **zero** Kubernetes CR dependency: `provision_api_key` → `verify_api_key_search` → `send_requests` (keys work) → `revoke_api_keys` → `verify_revoked_key_denied` (keys now denied). No `subscription` param passed at all, keeping it fully REST-only rather than pulling in a CR just to exercise the subscription-echo check (that check lives on the two scenarios that already need a CR for their own primary purpose instead).

## Consequences

**Positive:**
- Closes 5 of the 6 checklist rows in the API key lifecycle section using patterns already established elsewhere in this codebase (numeric-flag assertions, `_revoke_keys` extraction, registry aliasing) — no assertion-evaluator changes, no new CRD/RBAC surface at all.
- `scenarios/api_key_lifecycle.yaml` needs no `deploy/rbac-maas-*` grant beyond what `provision_api_key`/`send_requests` already required — the smallest-blast-radius scenario in the suite.
- The registry-alias pattern (same class, second name) is now available for any future scenario needing to reuse a task's exact behavior under a distinct UI label, without duplicating code.

**Negative:**
- `expiresAt`'s actual *value* (vs. the tenant's `maxExpirationDays`) is still a Gap — that comparison genuinely needs `MaasTenantConfig`, a CR, so it stays deliberately excluded from this CR-free scenario. A future scenario/assertion would need to accept that one CR dependency to close it.
- `/search` scoping-to-caller is now proven correct in the cases this harness *can* test, but the harder claim (a different caller's keys are excluded) is out of reach with a single SA identity — documented as an accepted limit, not silently ignored.
- Like every new scenario in this repo's recent history, `api_key_lifecycle` is unit-tested (mocked `httpx`) but not yet run against a live cluster — verify end-to-end before relying on its pass/fail result, especially the registry-alias fix (confirm the UI actually renders `verify_revoked_key_denied` as its own distinct chip, not a collision with the earlier `send_requests` one).

**Neutral:**
- `docs/architecture/empirical-verification-checklist.md`'s API key lifecycle section is updated to reflect all this; the two-layer access model's "policy without quota" open question (ADR-018) is untouched by this ADR.
