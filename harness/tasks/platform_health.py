import time

import httpx
from kubernetes import client as k8s_client

from harness.result import TaskResult
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY

_KUADRANT_GROUP = "kuadrant.io"
_KUADRANT_VERSION = "v1alpha1"
_GATEWAY_GROUP = "gateway.networking.k8s.io"
_GATEWAY_VERSION = "v1"

# Confirmed live on the cluster this repo targets — the one Gateway MaaS's
# own HTTPRoutes actually reference (there is a second, unrelated Gateway,
# data-science-gateway, in the same namespace — don't assume there's only
# one). Override via params if a different install names it differently.
_DEFAULT_GATEWAY_NAME = "maas-default-gateway"
_DEFAULT_GATEWAY_NAMESPACE = "openshift-ingress"


def _condition_true(conditions: list[dict], condition_type: str) -> bool:
    return any(c.get("type") == condition_type and c.get("status") == "True" for c in conditions)


class CheckModelHealthTask(Task):
    """Read-only cross-check of three CRs the MaaS Setup UI displays, against
    what they actually say about themselves — not a claim about live traffic,
    just that the resources exist and report healthy conditions (ADR-022,
    docs/architecture/empirical-verification-checklist.md). No writes, no
    cleanup needed.

    Resources are found by label selector, not an assumed generated name —
    ADR-009's lesson (a MaaSSubscription schema assumption shipped silently
    broken) applies just as well to a resource *name* pattern as to a schema.
    Scoped to internally-hosted (LLMInferenceService-backed) models only —
    ExternalModel routing is a separate, still-open checklist item.
    """

    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()
        model_name = str(self.params["model_name"])
        model_namespace = str(self.params["model_namespace"])
        gateway_name = str(self.params.get("gateway_name") or _DEFAULT_GATEWAY_NAME)
        gateway_namespace = str(self.params.get("gateway_namespace") or _DEFAULT_GATEWAY_NAMESPACE)

        api = k8s_client.CustomObjectsApi()

        trlp_items = api.list_namespaced_custom_object(
            group=_KUADRANT_GROUP,
            version=_KUADRANT_VERSION,
            namespace=model_namespace,
            plural="tokenratelimitpolicies",
            label_selector=f"maas.opendatahub.io/model={model_name}",
        ).get("items", [])
        trlp_found = bool(trlp_items)
        trlp_conditions = trlp_items[0].get("status", {}).get("conditions", []) if trlp_found else []
        ctx.shared_state["rate_limit_policy_status"] = {
            "found": int(trlp_found),
            "accepted": int(_condition_true(trlp_conditions, "Accepted")),
            "enforced": int(_condition_true(trlp_conditions, "Enforced")),
        }
        print(
            f"[check_model_health] TokenRateLimitPolicy for {model_namespace}/{model_name}: "
            f"{ctx.shared_state['rate_limit_policy_status']}",
            flush=True,
        )

        gateway = api.get_namespaced_custom_object(
            group=_GATEWAY_GROUP,
            version=_GATEWAY_VERSION,
            namespace=gateway_namespace,
            plural="gateways",
            name=gateway_name,
        )
        gw_conditions = gateway.get("status", {}).get("conditions", [])
        ctx.shared_state["gateway_status"] = {
            "programmed": int(_condition_true(gw_conditions, "Programmed")),
        }
        print(
            f"[check_model_health] Gateway {gateway_namespace}/{gateway_name}: "
            f"{ctx.shared_state['gateway_status']}",
            flush=True,
        )

        route_items = api.list_namespaced_custom_object(
            group=_GATEWAY_GROUP,
            version=_GATEWAY_VERSION,
            namespace=model_namespace,
            plural="httproutes",
            label_selector=f"app.kubernetes.io/name={model_name}",
        ).get("items", [])
        route_found = bool(route_items)
        owner_refs = route_items[0].get("metadata", {}).get("ownerReferences", []) if route_found else []
        owner_matches = any(
            ref.get("kind") == "LLMInferenceService" and ref.get("name") == model_name
            for ref in owner_refs
        )
        ctx.shared_state["http_route_status"] = {
            "found": int(route_found),
            "owner_ref_matches": int(owner_matches),
        }
        print(
            f"[check_model_health] HTTPRoute for {model_namespace}/{model_name}: "
            f"{ctx.shared_state['http_route_status']}",
            flush=True,
        )

        await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        pass


class CheckPlatformHealthTask(Task):
    """API-level platform health check — calls GET /v1/models with the SA
    token to confirm the MaaS endpoint is reachable and at least one model is
    registered. No Kubernetes client, no CR reads — entirely through the MaaS
    REST API, as an end user would experience it.
    """

    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()

        url = f"{ctx.maas_api_url}/v1/models"
        print(f"[check_platform_health] GET {url}", flush=True)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {ctx.sa_token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        models = data.get("data", [])
        model_count = len(models)
        ctx.shared_state["platform_health"] = {
            "model_count": model_count,
            "api_reachable": 1,
        }
        print(
            f"[check_platform_health] MaaS API reachable; {model_count} model(s) registered:",
            flush=True,
        )
        for m in models:
            print(
                f"  id={m.get('id')} owned_by={m.get('owned_by', '')}",
                flush=True,
            )
        await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        pass


REGISTRY["check_model_health"] = CheckModelHealthTask
REGISTRY["check_platform_health"] = CheckPlatformHealthTask
