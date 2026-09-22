import asyncio
import time
import traceback

from kubernetes import client as k8s_client

from harness.result import TaskResult
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY

_GROUP = "maas.opendatahub.io"
_VERSION = "v1alpha1"
_PLURAL = "maassubscriptions"

# High enough to win over any pre-existing subscription targeting the same
# model (upstream's recommended scheme tops out around 100 for prod tiers),
# so this scenario's behavior doesn't depend on what else happens to be
# configured on the cluster.
_DEFAULT_PRIORITY = 100

# Kuadrant's TokenRateLimitPolicy counts tokens per window, not requests —
# there is no literal "requests per second" field on MaaSSubscription (see
# ADR-009's Update section). Defaulting the window to 1 second makes
# `token_limit` directly comparable, unit-for-unit, to the harness's own
# `token_throughput_per_sec` measurement (harness/tasks/inference.py) with no
# conversion — pass a different `token_window` only if you also adjust what
# you compare `token_limit` against.
_DEFAULT_TOKEN_WINDOW = "1s"

# ServiceAccount tokens resolve to this group via Kubernetes TokenReview
# (confirmed live: `auth.identity.user.groups` includes `system:authenticated`
# for a ServiceAccount caller), which is also how the cluster's own sample
# subscriptions (simulator-free/simulator-premium) grant access — so this is
# the one group virtually guaranteed to actually match the harness's own
# identity without needing cluster-specific group names as a scenario input.
_DEFAULT_OWNER_GROUPS = ["system:authenticated"]

# Confirmed live: a MaaSSubscription just created/patched via the K8s API is
# accepted immediately, but the MaaS controller reconciles it asynchronously —
# calling POST /maas-api/v1/api-keys with `subscription` pinned to it right
# after creation can lose that race and get back
# `400 {"code":"subscription_not_ready","error":"subscription is unreconciled
# (no status.phase set)"}`. Poll for a non-empty status.phase before moving
# on, rather than assuming the create/patch call being accepted means the
# subscription is actually usable yet.
_DEFAULT_READY_MAX_WAIT_S = 30.0
_READY_POLL_INTERVAL_S = 2.0


async def _wait_for_subscription_ready(
    api: k8s_client.CustomObjectsApi,
    sub_name: str,
    namespace: str,
    max_wait_s: float,
    log_prefix: str,
) -> None:
    start = time.monotonic()
    while True:
        obj = _get_existing_subscription(api, sub_name, namespace)
        phase = (obj or {}).get("status", {}).get("phase")
        if phase:
            print(f"[{log_prefix}] {sub_name} reconciled, status.phase={phase!r}", flush=True)
            return
        elapsed = time.monotonic() - start
        if elapsed >= max_wait_s:
            print(
                f"[{log_prefix}] {sub_name} still unreconciled after {max_wait_s}s "
                "(no status.phase) — proceeding anyway; the next task will surface "
                "the real error if it's still not ready",
                flush=True,
            )
            return
        await asyncio.sleep(_READY_POLL_INTERVAL_S)


def _subscription_body(
    sub_name: str,
    namespace: str,
    priority: int,
    owner_groups: list[str],
    owner_users: list[str],
    model_name: str,
    model_namespace: str,
    token_limit: int,
    token_window: str,
) -> dict:
    # Real MaaSSubscription schema (confirmed live, see
    # docs/architecture/maas-domain-reference.md Catalog item A) — there is
    # no top-level `rpsLimit` field; rate limits are per-model, under
    # `modelRefs[].tokenRateLimits[]`.
    return {
        "apiVersion": f"{_GROUP}/{_VERSION}",
        "kind": "MaaSSubscription",
        "metadata": {"name": sub_name, "namespace": namespace},
        "spec": {
            "priority": priority,
            "owner": {
                "groups": [{"name": g} for g in owner_groups],
                "users": owner_users,
            },
            "modelRefs": [
                {
                    "name": model_name,
                    "namespace": model_namespace,
                    "tokenRateLimits": [{"limit": token_limit, "window": token_window}],
                }
            ],
        },
    }


def _get_existing_subscription(api: k8s_client.CustomObjectsApi, sub_name: str, namespace: str):
    try:
        return api.get_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=namespace, plural=_PLURAL, name=sub_name
        )
    except k8s_client.ApiException as exc:
        if exc.status == 404:
            return None
        raise


def _create_or_patch_subscription(
    api: k8s_client.CustomObjectsApi, sub_name: str, namespace: str, body: dict, existing
) -> None:
    if existing is None:
        api.create_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=namespace, plural=_PLURAL, body=body
        )
    else:
        api.patch_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=namespace, plural=_PLURAL,
            name=sub_name, body=body,
        )


def _cleanup_subscription(
    api: k8s_client.CustomObjectsApi, sub_name: str, namespace: str, original, created: bool
) -> None:
    if created:
        api.delete_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=namespace, plural=_PLURAL, name=sub_name
        )
    elif original is not None:
        api.replace_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=namespace, plural=_PLURAL,
            name=sub_name, body=original,
        )


class ApplyRateLimitSubscriptionTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()

        sub_name = str(self.params.get("subscription_name", "maaspal-test-subscription"))
        namespace = str(self.params["namespace"])
        model_name = str(self.params["model_name"])
        model_namespace = str(self.params["model_namespace"])
        token_limit = int(self.params.get("token_limit", 10))
        token_window = str(self.params.get("token_window") or _DEFAULT_TOKEN_WINDOW)
        priority = int(self.params.get("priority", _DEFAULT_PRIORITY))
        owner_groups = self.params.get("owner_groups") or _DEFAULT_OWNER_GROUPS
        owner_users = self.params.get("owner_users") or []
        ready_max_wait_s = float(self.params.get("ready_max_wait_s", _DEFAULT_READY_MAX_WAIT_S))

        api = k8s_client.CustomObjectsApi()
        existing = _get_existing_subscription(api, sub_name, namespace)
        ctx.shared_state["original_subscription"] = existing
        ctx.shared_state["_sub_created"] = existing is None

        body = _subscription_body(
            sub_name, namespace, priority, owner_groups, owner_users,
            model_name, model_namespace, token_limit, token_window,
        )
        _create_or_patch_subscription(api, sub_name, namespace, body, existing)
        print(
            f"[apply_rate_limit_subscription] {'created' if existing is None else 'patched'} "
            f"{sub_name} token_limit={token_limit}/{token_window} for {model_namespace}/{model_name}",
            flush=True,
        )
        await _wait_for_subscription_ready(
            api, sub_name, namespace, ready_max_wait_s, "apply_rate_limit_subscription"
        )

        ctx.shared_state["subscription_name"] = sub_name
        ctx.shared_state["subscription_namespace"] = namespace
        await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        sub_name = ctx.shared_state.get("subscription_name")
        namespace = ctx.shared_state.get("subscription_namespace")
        if not sub_name or not namespace:
            return

        api = k8s_client.CustomObjectsApi()
        original = ctx.shared_state.get("original_subscription")
        created = ctx.shared_state.get("_sub_created", False)

        try:
            _cleanup_subscription(api, sub_name, namespace, original, created)
            print(
                f"[apply_rate_limit_subscription] {'deleted' if created else 'restored'} {sub_name}",
                flush=True,
            )
        except Exception:
            print(
                f"[apply_rate_limit_subscription] cleanup FAILED\n{traceback.format_exc()}",
                flush=True,
            )


class ApplyPriorityTestSubscriptionsTask(Task):
    """Creates multiple MaaSSubscriptions in one task invocation, all sharing
    the same owner (so they compete for the same caller's auto-selection),
    each with its own priority/token_limit — used to empirically test that
    MaaS's auto-selection actually picks the highest-priority eligible
    subscription for a caller (ADR-021,
    docs/architecture/empirical-verification-checklist.md).

    A second YAML task entry for ApplyRateLimitSubscriptionTask (even under a
    different registered name) would NOT work here: that task's shared_state
    bookkeeping (subscription_name/_sub_created/original_subscription) is a
    fixed key, not namespaced per task instance — two instances in one
    scenario would silently clobber each other's cleanup state before
    cleanup() ever runs. This task tracks a *list* instead, one entry per
    subscription, so each gets cleaned up independently and correctly.
    """

    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()
        namespace = str(self.params["namespace"])
        model_name = str(self.params["model_name"])
        model_namespace = str(self.params["model_namespace"])
        owner_groups = self.params.get("owner_groups") or _DEFAULT_OWNER_GROUPS
        owner_users = self.params.get("owner_users") or []
        ready_max_wait_s = float(self.params.get("ready_max_wait_s", _DEFAULT_READY_MAX_WAIT_S))
        specs = self.params["subscriptions"]

        api = k8s_client.CustomObjectsApi()
        records = []
        for spec in specs:
            sub_name = str(spec["name"])
            priority = int(spec["priority"])
            token_limit = int(spec.get("token_limit", 10))
            token_window = str(spec.get("token_window") or _DEFAULT_TOKEN_WINDOW)

            existing = _get_existing_subscription(api, sub_name, namespace)
            body = _subscription_body(
                sub_name, namespace, priority, owner_groups, owner_users,
                model_name, model_namespace, token_limit, token_window,
            )
            _create_or_patch_subscription(api, sub_name, namespace, body, existing)
            print(
                f"[apply_priority_test_subscriptions] "
                f"{'created' if existing is None else 'patched'} {sub_name} "
                f"priority={priority} token_limit={token_limit}/{token_window}",
                flush=True,
            )
            await _wait_for_subscription_ready(
                api, sub_name, namespace, ready_max_wait_s, "apply_priority_test_subscriptions"
            )
            records.append(
                {
                    "name": sub_name,
                    "namespace": namespace,
                    "original": existing,
                    "created": existing is None,
                }
            )

        ctx.shared_state["priority_test_subscriptions"] = records
        await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        records = ctx.shared_state.get("priority_test_subscriptions", [])
        if not records:
            return

        api = k8s_client.CustomObjectsApi()
        for rec in records:
            try:
                _cleanup_subscription(api, rec["name"], rec["namespace"], rec["original"], rec["created"])
                print(
                    f"[apply_priority_test_subscriptions] "
                    f"{'deleted' if rec['created'] else 'restored'} {rec['name']}",
                    flush=True,
                )
            except Exception:
                print(
                    f"[apply_priority_test_subscriptions] cleanup FAILED for {rec['name']}\n"
                    f"{traceback.format_exc()}",
                    flush=True,
                )


REGISTRY["apply_rate_limit_subscription"] = ApplyRateLimitSubscriptionTask
REGISTRY["apply_priority_test_subscriptions"] = ApplyPriorityTestSubscriptionsTask
