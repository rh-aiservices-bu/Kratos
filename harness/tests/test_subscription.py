from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from harness.tasks.base import TaskContext
from harness.tasks.subscription import ApplyRateLimitSubscriptionTask


def _make_ctx(shared_state: dict | None = None) -> TaskContext:
    async def _emit() -> None:
        pass

    return TaskContext(
        run_id="test-001",
        scenario_name="test",
        maas_api_url="http://maas.test",
        sa_token="test-token",
        shared_state=shared_state or {},
        config={"NAMESPACE": "test-ns"},
        assertions={},
        emit_assertion_state=_emit,
    )


def _api_exc(status: int) -> ApiException:
    return ApiException(status=status)


async def test_creates_cr_when_not_existing() -> None:
    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api
        api.get_namespaced_custom_object.side_effect = _api_exc(404)

        task = ApplyRateLimitSubscriptionTask(
            "apply_rate_limit_subscription",
            {"rps_limit": "10", "subscription_name": "test-sub"},
        )
        ctx = _make_ctx()
        result = await task.run(ctx)

    assert result.status == "PASS"
    assert ctx.shared_state["original_subscription"] is None
    assert ctx.shared_state["_sub_created"] is True
    api.create_namespaced_custom_object.assert_called_once()
    api.patch_namespaced_custom_object.assert_not_called()


async def test_patches_cr_when_existing() -> None:
    existing = {"apiVersion": "maas.opendatahub.io/v1alpha1", "spec": {"rpsLimit": 5}}

    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api
        api.get_namespaced_custom_object.return_value = existing

        task = ApplyRateLimitSubscriptionTask(
            "apply_rate_limit_subscription",
            {"rps_limit": "20", "subscription_name": "test-sub"},
        )
        ctx = _make_ctx()
        result = await task.run(ctx)

    assert result.status == "PASS"
    assert ctx.shared_state["original_subscription"] == existing
    assert ctx.shared_state["_sub_created"] is False
    api.patch_namespaced_custom_object.assert_called_once()
    api.create_namespaced_custom_object.assert_not_called()


async def test_cleanup_deletes_when_created() -> None:
    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api

        ctx = _make_ctx(
            {
                "original_subscription": None,
                "_sub_created": True,
                "subscription_name": "test-sub",
                "subscription_namespace": "test-ns",
            }
        )
        task = ApplyRateLimitSubscriptionTask("apply_rate_limit_subscription", {})
        await task.cleanup(ctx)

    api.delete_namespaced_custom_object.assert_called_once()
    api.replace_namespaced_custom_object.assert_not_called()


async def test_cleanup_restores_when_preexisting() -> None:
    original = {"apiVersion": "maas.opendatahub.io/v1alpha1", "spec": {"rpsLimit": 5}}

    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api

        ctx = _make_ctx(
            {
                "original_subscription": original,
                "_sub_created": False,
                "subscription_name": "test-sub",
                "subscription_namespace": "test-ns",
            }
        )
        task = ApplyRateLimitSubscriptionTask("apply_rate_limit_subscription", {})
        await task.cleanup(ctx)

    api.replace_namespaced_custom_object.assert_called_once()
    api.delete_namespaced_custom_object.assert_not_called()


async def test_cleanup_noop_when_no_state() -> None:
    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api

        ctx = _make_ctx()
        task = ApplyRateLimitSubscriptionTask("apply_rate_limit_subscription", {})
        await task.cleanup(ctx)

    api.delete_namespaced_custom_object.assert_not_called()
    api.replace_namespaced_custom_object.assert_not_called()


async def test_non_404_api_exception_propagates() -> None:
    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api
        api.get_namespaced_custom_object.side_effect = _api_exc(403)

        task = ApplyRateLimitSubscriptionTask(
            "apply_rate_limit_subscription",
            {"rps_limit": "10"},
        )
        ctx = _make_ctx()
        with pytest.raises(ApiException):
            await task.run(ctx)
