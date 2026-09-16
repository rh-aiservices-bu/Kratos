from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from harness.tasks.base import TaskContext
from harness.tasks.subscription import ApplyRateLimitSubscriptionTask

_PARAMS = {
    "subscription_name": "test-sub",
    "namespace": "models-as-a-service",
    "model_name": "facebook-opt-125m-simulated",
    "model_namespace": "llm",
    "token_limit": "10",
}


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


def _body_from(mock_call) -> dict:
    return mock_call.call_args.kwargs["body"]


async def test_creates_cr_when_not_existing() -> None:
    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api
        api.get_namespaced_custom_object.side_effect = _api_exc(404)

        task = ApplyRateLimitSubscriptionTask("apply_rate_limit_subscription", _PARAMS)
        ctx = _make_ctx()
        result = await task.run(ctx)

    assert result.status == "PASS"
    assert ctx.shared_state["original_subscription"] is None
    assert ctx.shared_state["_sub_created"] is True
    api.create_namespaced_custom_object.assert_called_once()
    api.patch_namespaced_custom_object.assert_not_called()

    body = _body_from(api.create_namespaced_custom_object)
    assert body["metadata"]["namespace"] == "models-as-a-service"
    assert "rpsLimit" not in body["spec"]
    assert body["spec"]["priority"] == 100
    assert body["spec"]["owner"]["groups"] == [{"name": "system:authenticated"}]
    model_ref = body["spec"]["modelRefs"][0]
    assert model_ref["name"] == "facebook-opt-125m-simulated"
    assert model_ref["namespace"] == "llm"
    assert model_ref["tokenRateLimits"] == [{"limit": 10, "window": "1s"}]


async def test_custom_priority_owner_and_window() -> None:
    params = {
        **_PARAMS,
        "priority": "5",
        "owner_groups": ["team-a"],
        "owner_users": ["alice"],
        "token_window": "1m",
    }
    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api
        api.get_namespaced_custom_object.side_effect = _api_exc(404)

        task = ApplyRateLimitSubscriptionTask("apply_rate_limit_subscription", params)
        await task.run(_make_ctx())

    body = _body_from(api.create_namespaced_custom_object)
    assert body["spec"]["priority"] == 5
    assert body["spec"]["owner"]["groups"] == [{"name": "team-a"}]
    assert body["spec"]["owner"]["users"] == ["alice"]
    assert body["spec"]["modelRefs"][0]["tokenRateLimits"] == [{"limit": 10, "window": "1m"}]


async def test_patches_cr_when_existing() -> None:
    existing = {
        "apiVersion": "maas.opendatahub.io/v1alpha1",
        "spec": {"priority": 100, "owner": {"groups": [], "users": []}, "modelRefs": []},
    }

    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api
        api.get_namespaced_custom_object.return_value = existing

        task = ApplyRateLimitSubscriptionTask(
            "apply_rate_limit_subscription", {**_PARAMS, "token_limit": "20"}
        )
        result = await task.run(_make_ctx())

    assert result.status == "PASS"
    assert api.patch_namespaced_custom_object.call_count == 1
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
                "subscription_namespace": "models-as-a-service",
            }
        )
        task = ApplyRateLimitSubscriptionTask("apply_rate_limit_subscription", {})
        await task.cleanup(ctx)

    api.delete_namespaced_custom_object.assert_called_once()
    api.replace_namespaced_custom_object.assert_not_called()


async def test_cleanup_restores_when_preexisting() -> None:
    original = {"apiVersion": "maas.opendatahub.io/v1alpha1", "spec": {"priority": 100}}

    with patch("harness.tasks.subscription.k8s_client.CustomObjectsApi") as mock_cls:
        api = MagicMock()
        mock_cls.return_value = api

        ctx = _make_ctx(
            {
                "original_subscription": original,
                "_sub_created": False,
                "subscription_name": "test-sub",
                "subscription_namespace": "models-as-a-service",
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

        task = ApplyRateLimitSubscriptionTask("apply_rate_limit_subscription", _PARAMS)
        with pytest.raises(ApiException):
            await task.run(_make_ctx())


async def test_missing_required_param_raises() -> None:
    task = ApplyRateLimitSubscriptionTask(
        "apply_rate_limit_subscription", {"subscription_name": "test-sub"}
    )
    with pytest.raises(KeyError):
        await task.run(_make_ctx())
