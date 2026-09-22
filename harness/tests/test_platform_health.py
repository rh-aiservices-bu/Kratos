from unittest.mock import MagicMock, patch

from harness.tasks.base import TaskContext
from harness.tasks.platform_health import CheckModelHealthTask

_PARAMS = {
    "model_name": "facebook-opt-125m-simulated",
    "model_namespace": "llm",
}

_HEALTHY_TRLP = {
    "status": {
        "conditions": [
            {"type": "Accepted", "status": "True"},
            {"type": "Enforced", "status": "True"},
        ]
    }
}

_PROGRAMMED_GATEWAY = {
    "status": {
        "conditions": [
            {"type": "Accepted", "status": "True"},
            {"type": "Programmed", "status": "True"},
        ]
    }
}

_MATCHING_ROUTE = {
    "metadata": {
        "ownerReferences": [
            {"kind": "LLMInferenceService", "name": "facebook-opt-125m-simulated"}
        ]
    }
}


def _make_ctx() -> TaskContext:
    async def _emit() -> None:
        pass

    return TaskContext(
        run_id="test-001",
        scenario_name="test",
        maas_api_url="http://maas.test",
        sa_token="test-token",
        shared_state={},
        config={},
        assertions={},
        emit_assertion_state=_emit,
    )


def _mock_api(*, trlp_items=None, gateway=None, route_items=None) -> MagicMock:
    api = MagicMock()
    api.list_namespaced_custom_object.side_effect = [
        {"items": trlp_items if trlp_items is not None else [_HEALTHY_TRLP]},
        {"items": route_items if route_items is not None else [_MATCHING_ROUTE]},
    ]
    api.get_namespaced_custom_object.return_value = (
        gateway if gateway is not None else _PROGRAMMED_GATEWAY
    )
    return api


async def test_all_healthy() -> None:
    with patch("harness.tasks.platform_health.k8s_client.CustomObjectsApi") as mock_cls:
        api = _mock_api()
        mock_cls.return_value = api

        task = CheckModelHealthTask("check_model_health",_PARAMS)
        ctx = _make_ctx()
        result = await task.run(ctx)

    assert result.status == "PASS"
    assert ctx.shared_state["rate_limit_policy_status"] == {
        "found": 1, "accepted": 1, "enforced": 1,
    }
    assert ctx.shared_state["gateway_status"] == {"programmed": 1}
    assert ctx.shared_state["http_route_status"] == {"found": 1, "owner_ref_matches": 1}


async def test_token_rate_limit_policy_not_found() -> None:
    with patch("harness.tasks.platform_health.k8s_client.CustomObjectsApi") as mock_cls:
        api = _mock_api(trlp_items=[])
        mock_cls.return_value = api

        task = CheckModelHealthTask("check_model_health",_PARAMS)
        ctx = _make_ctx()
        await task.run(ctx)

    assert ctx.shared_state["rate_limit_policy_status"] == {
        "found": 0, "accepted": 0, "enforced": 0,
    }


async def test_token_rate_limit_policy_not_enforced() -> None:
    unenforced = {
        "status": {
            "conditions": [
                {"type": "Accepted", "status": "True"},
                {"type": "Enforced", "status": "False"},
            ]
        }
    }
    with patch("harness.tasks.platform_health.k8s_client.CustomObjectsApi") as mock_cls:
        api = _mock_api(trlp_items=[unenforced])
        mock_cls.return_value = api

        task = CheckModelHealthTask("check_model_health",_PARAMS)
        ctx = _make_ctx()
        await task.run(ctx)

    status = ctx.shared_state["rate_limit_policy_status"]
    assert status["accepted"] == 1
    assert status["enforced"] == 0


async def test_gateway_not_programmed() -> None:
    unprogrammed = {"status": {"conditions": [{"type": "Accepted", "status": "True"}]}}
    with patch("harness.tasks.platform_health.k8s_client.CustomObjectsApi") as mock_cls:
        api = _mock_api(gateway=unprogrammed)
        mock_cls.return_value = api

        task = CheckModelHealthTask("check_model_health",_PARAMS)
        ctx = _make_ctx()
        await task.run(ctx)

    assert ctx.shared_state["gateway_status"] == {"programmed": 0}


async def test_http_route_not_found() -> None:
    with patch("harness.tasks.platform_health.k8s_client.CustomObjectsApi") as mock_cls:
        api = _mock_api(route_items=[])
        mock_cls.return_value = api

        task = CheckModelHealthTask("check_model_health",_PARAMS)
        ctx = _make_ctx()
        await task.run(ctx)

    assert ctx.shared_state["http_route_status"] == {"found": 0, "owner_ref_matches": 0}


async def test_http_route_owner_mismatch() -> None:
    wrong_owner = {
        "metadata": {"ownerReferences": [{"kind": "LLMInferenceService", "name": "some-other-model"}]}
    }
    with patch("harness.tasks.platform_health.k8s_client.CustomObjectsApi") as mock_cls:
        api = _mock_api(route_items=[wrong_owner])
        mock_cls.return_value = api

        task = CheckModelHealthTask("check_model_health",_PARAMS)
        ctx = _make_ctx()
        await task.run(ctx)

    status = ctx.shared_state["http_route_status"]
    assert status["found"] == 1
    assert status["owner_ref_matches"] == 0


async def test_uses_label_selectors_scoped_to_model_namespace() -> None:
    """Resources are found by label, in the model's own namespace — not an
    assumed name pattern (ADR-009's lesson applies to names too)."""
    with patch("harness.tasks.platform_health.k8s_client.CustomObjectsApi") as mock_cls:
        api = _mock_api()
        mock_cls.return_value = api

        task = CheckModelHealthTask("check_model_health",_PARAMS)
        await task.run(_make_ctx())

    trlp_call, route_call = api.list_namespaced_custom_object.call_args_list
    assert trlp_call.kwargs["namespace"] == "llm"
    assert trlp_call.kwargs["label_selector"] == "maas.opendatahub.io/model=facebook-opt-125m-simulated"
    assert route_call.kwargs["namespace"] == "llm"
    assert route_call.kwargs["label_selector"] == "app.kubernetes.io/name=facebook-opt-125m-simulated"


async def test_gateway_defaults_to_confirmed_live_name() -> None:
    with patch("harness.tasks.platform_health.k8s_client.CustomObjectsApi") as mock_cls:
        api = _mock_api()
        mock_cls.return_value = api

        task = CheckModelHealthTask("check_model_health",_PARAMS)
        await task.run(_make_ctx())

    gw_call = api.get_namespaced_custom_object.call_args
    assert gw_call.kwargs["name"] == "maas-default-gateway"
    assert gw_call.kwargs["namespace"] == "openshift-ingress"


async def test_gateway_name_overridable() -> None:
    with patch("harness.tasks.platform_health.k8s_client.CustomObjectsApi") as mock_cls:
        api = _mock_api()
        mock_cls.return_value = api

        task = CheckModelHealthTask(
            "check_model_health",
            {**_PARAMS, "gateway_name": "custom-gateway", "gateway_namespace": "custom-ns"},
        )
        await task.run(_make_ctx())

    gw_call = api.get_namespaced_custom_object.call_args
    assert gw_call.kwargs["name"] == "custom-gateway"
    assert gw_call.kwargs["namespace"] == "custom-ns"
