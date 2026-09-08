from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from harness.result import TaskResult


@dataclass
class TaskContext:
    run_id: str
    scenario_name: str
    maas_api_url: str
    sa_token: str
    shared_state: dict
    config: dict
    assertions: dict[str, str]
    emit_assertion_state: Callable[[], Awaitable[None]]


class Task(ABC):
    def __init__(self, name: str, params: dict) -> None:
        self.name = name
        self.params = params

    @abstractmethod
    async def run(self, ctx: TaskContext) -> TaskResult: ...

    @abstractmethod
    async def cleanup(self, ctx: TaskContext) -> None: ...
