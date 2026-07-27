from __future__ import annotations

from typing import TYPE_CHECKING

from .compute_service import UsageComputePayload, UsageComputeService

if TYPE_CHECKING:
    from .controller import UsageController, UsageControllerMixin
    from .print_service import UsagePrintContext, UsagePrintService
    from runtime.presentation.views.usage_page import UsagePage

__all__ = (
    "UsageComputePayload",
    "UsageComputeService",
    "UsageController",
    "UsageControllerMixin",
    "UsagePage",
    "UsagePrintContext",
    "UsagePrintService",
)


def __getattr__(name: str):
    if name in {"UsageController", "UsageControllerMixin"}:
        from .controller import UsageController, UsageControllerMixin
        return {
            "UsageController": UsageController,
            "UsageControllerMixin": UsageControllerMixin,
        }[name]
    if name in {"UsagePrintContext", "UsagePrintService"}:
        from .print_service import UsagePrintContext, UsagePrintService
        return {
            "UsagePrintContext": UsagePrintContext,
            "UsagePrintService": UsagePrintService,
        }[name]
    if name == "UsagePage":
        from runtime.presentation.views.usage_page import UsagePage
        return UsagePage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
