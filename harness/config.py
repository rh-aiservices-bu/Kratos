import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

_INTERP_RE = re.compile(r"\$\{config\.([^}]+)\}")


def _resolve(value: Any, config: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            key = m.group(1)
            if key not in config:
                raise KeyError(
                    f"Config interpolation failed: key {key!r} not defined. "
                    f"Available: {sorted(config)}"
                )
            return str(config[key])

        return _INTERP_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _resolve(v, config) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(item, config) for item in value]
    return value


def load_scenario(path: str) -> dict:
    """Load and resolve a scenario YAML.

    Config precedence (highest → lowest):
      1. KRATOS_CONFIG_OVERRIDES env var (user-provided via UI)
      2. Scenario YAML ``config:`` section
      3. Environment variables (injected from global ConfigMap)
    """
    raw: dict = yaml.safe_load(Path(path).read_text())

    global_config: dict[str, Any] = dict(os.environ)
    scenario_config: dict[str, Any] = raw.get("config", {}) or {}

    user_overrides: dict[str, Any] = {}
    try:
        user_overrides = json.loads(os.environ.get("KRATOS_CONFIG_OVERRIDES", "{}")) or {}
    except Exception:
        pass

    merged_config: dict[str, Any] = {**global_config, **scenario_config, **user_overrides}

    resolved_tasks = []
    for task in raw.get("tasks", []) or []:
        resolved_params = _resolve(task.get("params") or {}, merged_config)
        resolved_task_assertions = _resolve(task.get("assertions") or {}, merged_config)
        resolved_tasks.append({**task, "params": resolved_params, "assertions": resolved_task_assertions})

    resolved_assertions = _resolve(raw.get("assertions") or {}, merged_config)
    resolved_metrics_queries = _resolve(raw.get("metrics_queries") or {}, merged_config)

    return {
        **raw,
        "tasks": resolved_tasks,
        "assertions": resolved_assertions,
        "metrics_queries": resolved_metrics_queries,
        "_resolved_config": merged_config,
    }
