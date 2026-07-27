from __future__ import annotations
from PyQt5.QtGui import QColor
from runtime.presentation.usage.print_support import UsagePrintContext
from runtime.presentation.usage.print_support import UsagePrintMetricsMixin
from runtime.presentation.usage.print_support import UsagePrintPrinterMixin
from runtime.presentation.usage.print_support import UsagePrintRenderMixin


class UsagePrintService(
    UsagePrintPrinterMixin, UsagePrintMetricsMixin, UsagePrintRenderMixin
):
    TITLE_COLOR = QColor("#0f172a")
    MUTED_TEXT = QColor("#475569")
    GRID_COLOR = QColor("#cbd5e1")
    HEADER_BG = QColor("#12326b")
    HEADER_TEXT = QColor("#ffffff")
    ALT_ROW_BG = QColor("#f3f6fa")
    ROW_TEXT = QColor("#0f172a")
    ACCENT_COLOR = QColor("#e31e24")
    PAGE_MARGIN_MM = 5.0
    PRINT_DPI_FALLBACK = 300
    _HEADER_FALLBACKS = (
        "ITEM CODE",
        "PRODUCT NAME",
        "BEGINNING BALANCE",
        "PURCHASE",
        "TOTAL AVAILABLE",
        "CONSUMED",
        "UOM",
        "ACTUAL CONSUMPTION",
    )


__all__ = ["UsagePrintContext", "UsagePrintService"]
