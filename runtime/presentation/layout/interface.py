from __future__ import annotations
from typing import Any
from runtime.presentation.layout.tables import polish_tables
from runtime.presentation.layout.text import polish_text_visibility


def polish_interface(root: Any, *, window_width: int | None = None) -> None:
    polish_text_visibility(root)
    polish_tables(root, window_width=window_width)
