import textwrap
from pathlib import Path

import pytest

from harness.config import load_scenario


def _write(tmp_path: Path, content: str) -> str:
    f = tmp_path / "scenario.yaml"
    f.write_text(textwrap.dedent(content))
    return str(f)


def test_basic_load(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        name: test
        description: "basic test"
        config:
          count: 10
        tasks: []
        assertions: {}
    """)
    s = load_scenario(path)
    assert s["name"] == "test"
    assert s["_resolved_config"]["count"] == 10


def test_interpolation_in_params(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        name: test
        config:
          count: 100
        tasks:
          - name: stub_pass
            params:
              n: "${config.count}"
        assertions: {}
    """)
    s = load_scenario(path)
    assert s["tasks"][0]["params"]["n"] == "100"


def test_interpolation_in_assertions(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        name: test
        config:
          limit: 10
        tasks: []
        assertions:
          throughput_rps: "<= ${config.limit}"
    """)
    s = load_scenario(path)
    assert s["assertions"]["throughput_rps"] == "<= 10"


def test_scenario_config_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAAS_API_URL", "https://global.example.com")
    path = _write(tmp_path, """
        name: test
        config:
          MAAS_API_URL: "https://local.example.com"
        tasks: []
        assertions: {}
    """)
    s = load_scenario(path)
    assert s["_resolved_config"]["MAAS_API_URL"] == "https://local.example.com"


def test_env_var_accessible_via_interpolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_TOKEN", "abc123")
    path = _write(tmp_path, """
        name: test
        config: {}
        tasks:
          - name: stub_pass
            params:
              token: "${config.MY_TOKEN}"
        assertions: {}
    """)
    s = load_scenario(path)
    assert s["tasks"][0]["params"]["token"] == "abc123"


def test_missing_key_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        name: test
        config: {}
        tasks:
          - name: stub_pass
            params:
              n: "${config.missing_key}"
        assertions: {}
    """)
    with pytest.raises(KeyError, match="missing_key"):
        load_scenario(path)


def test_interpolation_in_metrics_queries(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        name: test
        config:
          limitador_namespace: "llm/some-route"
        tasks: []
        metrics_queries:
          total_requests: 'sum(authorized_calls{limitador_namespace="${config.limitador_namespace}"})'
        assertions: {}
    """)
    s = load_scenario(path)
    assert s["metrics_queries"]["total_requests"] == 'sum(authorized_calls{limitador_namespace="llm/some-route"})'


def test_metrics_queries_defaults_to_empty_dict(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        name: test
        config: {}
        tasks: []
        assertions: {}
    """)
    s = load_scenario(path)
    assert s["metrics_queries"] == {}


def test_no_interpolation_in_non_string_values(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        name: test
        config:
          count: 5
        tasks:
          - name: stub_pass
            params:
              n: 42
        assertions: {}
    """)
    s = load_scenario(path)
    assert s["tasks"][0]["params"]["n"] == 42
