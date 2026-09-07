import argparse
import asyncio
import dataclasses
import json
from pathlib import Path

from harness.runner import ScenarioRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Kratos scenario runner")
    parser.add_argument("--scenario", required=True, help="Path to scenario YAML")
    parser.add_argument("--run-id", required=True, dest="run_id", help="Unique run identifier")
    args = parser.parse_args()

    runner = ScenarioRunner(scenario_path=args.scenario, run_id=args.run_id)
    result = asyncio.run(runner.run())

    output_path = Path(f"/data/results/{args.run_id}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dataclasses.asdict(result), indent=2))

    print(f"[harness] result written to {output_path}", flush=True)
    print(f"[harness] status: {result.status}", flush=True)


if __name__ == "__main__":
    main()
