from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LifecycleState(str, Enum):
    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    BACKGROUND = "background"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(slots=True)
class LifecycleReport:
    operation: str
    completed_steps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def successful(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class RegisteredResource:
    name: str
    resource: Any
    stop_method: str = "stop"
    wait_method: str | None = "wait"
    timeout_seconds: float = 5.0
