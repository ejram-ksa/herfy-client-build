from __future__ import annotations
from runtime.shared.settings.config import _

TRACKING_HEADER_KEYS = (
    "Branch",
    "Material",
    "Product Name",
    "Qty",
    "Production Date",
    "Expiry Date",
    "Status",
    "Actions",
)


def tracking_headers() -> tuple[str, ...]:
    return tuple((_(key) for key in TRACKING_HEADER_KEYS))


TRACKING_HEADERS = TRACKING_HEADER_KEYS
COL_BRANCH = 0
COL_MATERIAL = 1
COL_NAME = 2
COL_QTY = 3
COL_PRODUCTION = 4
COL_EXPIRY = 5
COL_STATUS = 6
COL_ACTIONS = 7
USAGE_HEADER_KEYS = (
    "Material",
    "Product Name",
    "Receipts",
    "Beginning",
    "Total",
    "Available Qty (Enter)",
    "UOM",
    "Actual Usage",
)


def usage_headers() -> tuple[str, ...]:
    return tuple((_(key) for key in USAGE_HEADER_KEYS))


USAGE_PRINT_HEADER_KEYS = (
    "Material No.",
    "Product Name",
    "Receipts",
    "Opening",
    "Total",
    "Available Qty",
    "UOM",
    "Actual Usage",
)


def usage_print_headers() -> tuple[str, ...]:
    return tuple((_(key) for key in USAGE_PRINT_HEADER_KEYS))


HEADERS_USAGE = USAGE_HEADER_KEYS
COL_R = 2
COL_B = 3
COL_T = 4
COL_H = 5
COL_UOM = 6
COL_U = 7
