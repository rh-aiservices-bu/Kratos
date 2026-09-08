import time

from kubernetes import client as k8s_client

from harness.result import TaskResult
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY

_GROUP = "maas.opendatahub.io"
_VERSION = "v1alpha1"
_PLURAL = "maassubscriptions"


class ApplyRateLimitSubscriptionTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()

        rps_limit = int(self.params.get("rps_limit", 10))
        sub_name = str(self.params.get("subscription_name", "kratos-test-subscription"))
        namespace = str(self.params.get("namespace") or ctx.config.get("NAMESPACE", "default"))

        api = k8s_client.CustomObjectsApi()

        try:
            existing = api.get_namespaced_custom_object(
                group=_GROUP,
                version=_VERSION,
                namespace=namespace,
                plural=_PLURAL,
                name=sub_name,
            )
            ctx.shared_state["original_subscription"] = existing
            ctx.shared_state["_sub_created"] = False
        except k8s_client.ApiException as exc:
            if exc.status == 404:
                ctx.shared_state["original_subscription"] = None
                ctx.shared_state["_sub_created"] = True
            else:
                raise

        body = {
            "apiVersion": f"{_GROUP}/{_VERSION}",
            "kind": "MaaSSubscription",
            "metadata": {"name": sub_name, "namespace": namespace},
            "spec": {"rpsLimit": rps_limit},
        }

        if ctx.shared_state["_sub_created"]:
            api.create_namespaced_custom_object(
                group=_GROUP, version=_VERSION, namespace=namespace, plural=_PLURAL, body=body
            )
            print(
                f"[apply_rate_limit_subscription] created {sub_name} rps_limit={rps_limit}",
                flush=True,
            )
        else:
            api.patch_namespaced_custom_object(
                group=_GROUP,
                version=_VERSION,
                namespace=namespace,
                plural=_PLURAL,
                name=sub_name,
                body=body,
            )
            print(
                f"[apply_rate_limit_subscription] patched {sub_name} rps_limit={rps_limit}",
                flush=True,
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
            if created:
                api.delete_namespaced_custom_object(
                    group=_GROUP,
                    version=_VERSION,
                    namespace=namespace,
                    plural=_PLURAL,
                    name=sub_name,
                )
                print(f"[apply_rate_limit_subscription] deleted {sub_name}", flush=True)
            elif original is not None:
                api.replace_namespaced_custom_object(
                    group=_GROUP,
                    version=_VERSION,
                    namespace=namespace,
                    plural=_PLURAL,
                    name=sub_name,
                    body=original,
                )
                print(f"[apply_rate_limit_subscription] restored {sub_name}", flush=True)
        except Exception as exc:
            print(f"[apply_rate_limit_subscription] cleanup warning: {exc}", flush=True)


REGISTRY["apply_rate_limit_subscription"] = ApplyRateLimitSubscriptionTask
