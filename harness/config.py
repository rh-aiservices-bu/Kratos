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
      1. Scenario YAML ``config:`` section
      2. Environment variables (injected from global ConfigMap)
    """
    raw: dict = yaml.safe_load(Path(path).read_text())

    global_config: dict[str, Any] = dict(os.environ)
    scenario_config: dict[str, Any] = raw.get("config", {}) or {}
    merged_config: dict[str, Any] = {**global_config, **scenario_config}

    resolved_tasks = []
    for task in raw.get("tasks", []) or []:
        resolved_params = _resolve(task.get("params") or {}, merged_config)
        resolved_tasks.append({**task, "params": resolved_params})

    resolved_assertions = _resolve(raw.get("assertions") or {}, merged_config)

    return {
        **raw,
        "tasks": resolved_tasks,
        "assertions": resolved_assertions,
        "_resolved_config": merged_config,
    }
