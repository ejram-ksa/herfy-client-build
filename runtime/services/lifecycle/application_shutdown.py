from __future__ import annotations

from dataclasses import dataclass

from runtime.services.lifecycle.application_lifecycle import ApplicationLifecycle
from runtime.services.lifecycle.models import LifecycleReport


@dataclass(slots=True)
class ApplicationShutdown:
    lifecycle: ApplicationLifecycle

    def execute(self) -> LifecycleReport:
        return self.lifecycle.shutdown()
