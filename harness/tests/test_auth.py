import json

import pytest
from pytest_httpx import HTTPXMock

from harness.tasks.auth import ProvisionApiKeyTask
from harness.tasks.base import TaskContext


def _make_ctx(shared_state: dict | None = None) -> TaskContext:
    async def _emit() -> None:
        pass

    return TaskContext(
        run_id="test-001",
        scenario_name="test",
        maas_api_url="http://maas.test",
        sa_token="test-token",
        shared_state=shared_state or {},
        config={},
        assertions={},
        emit_assertion_state=_emit,
    )


async def test_provision_api_key_appends_to_shared_state(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://maas.test/maas-api/v1/api-keys",
        method="POST",
        json={"id": "key-123", "key": "sk-oai-abc"},
    )

    task = ProvisionApiKeyTask("provision_api_key", {"key_name": "test-key"})
    ctx = _make_ctx()
    result = await task.run(ctx)

    assert result.status == "PASS"
    assert ctx.shared_state["api_keys"] == [{"id": "key-123", "key": "sk-oai-abc"}]


async def test_provision_api_key_accumulates_multiple_keys(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://maas.test/maas-api/v1/api-keys",
        method="POST",
        json={"id": "key-1", "key": "sk-1"},
    )
    httpx_mock.add_response(
        url="http://maas.test/maas-api/v1/api-keys",
        method="POST",
        json={"id": "key-2", "key": "sk-2"},
    )

    task = ProvisionApiKeyTask("provision_api_key", {"key_name": "test-key"})
    ctx = _make_ctx()
    await task.run(ctx)
    await task.run(ctx)

    assert len(ctx.shared_state["api_keys"]) == 2


async def test_provision_api_key_cleanup_bulk_revokes(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://maas.test/maas-api/v1/api-keys/bulk-revoke",
        method="POST",
        json={"revoked": 2},
    )

    ctx = _make_ctx(
        {"api_keys": [{"id": "id-1", "key": "sk-1"}, {"id": "id-2", "key": "sk-2"}]}
    )
    task = ProvisionApiKeyTask("provision_api_key", {})
    await task.cleanup(ctx)

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert sorted(body["ids"]) == ["id-1", "id-2"]


async def test_provision_api_key_cleanup_noop_when_empty() -> None:
    ctx = _make_ctx({"api_keys": []})
    task = ProvisionApiKeyTask("provision_api_key", {})
    await task.cleanup(ctx)


async def test_provision_api_key_uses_default_name(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://maas.test/maas-api/v1/api-keys",
        method="POST",
        json={"id": "key-xyz", "key": "sk-oai-xyz"},
    )

    task = ProvisionApiKeyTask("provision_api_key", {})
    ctx = _make_ctx()
    result = await task.run(ctx)

    assert result.status == "PASS"
    req = httpx_mock.get_requests()[0]
    body = json.loads(req.content)
    assert body["name"].startswith("kratos-")
