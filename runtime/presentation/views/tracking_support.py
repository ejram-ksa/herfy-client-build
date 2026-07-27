from __future__ import annotations
from collections.abc import Iterable
from dataclasses import dataclass
from runtime.presentation.layout.profiles import resolve_fluid_toolbar_mode


@dataclass(frozen=True, slots=True)
class ToolbarItemPlacement:
    name: str
    row: int
    column: int
    row_span: int = 1
    column_span: int = 1


@dataclass(frozen=True, slots=True)
class ToolbarLayoutSpec:
    mode: str
    placements: tuple[ToolbarItemPlacement, ...]
    column_stretches: tuple[int, ...]


TOOLBAR_MODES = frozenset({"wide", "compact"})
_LAYOUTS = {
    "wide": ToolbarLayoutSpec(
        "wide",
        (
            ToolbarItemPlacement("branch_field", 0, 0),
            ToolbarItemPlacement("product_field", 0, 1),
            ToolbarItemPlacement("production_field", 0, 2),
            ToolbarItemPlacement("expiry_field", 0, 3),
            ToolbarItemPlacement("quantity_field", 0, 4),
            ToolbarItemPlacement("action_field", 0, 5),
        ),
        (0, 1, 0, 0, 0, 0),
    ),
    "compact": ToolbarLayoutSpec(
        "compact",
        (
            ToolbarItemPlacement("branch_field", 0, 0),
            ToolbarItemPlacement("product_field", 0, 1),
            ToolbarItemPlacement("production_field", 0, 2),
            ToolbarItemPlacement("expiry_field", 0, 3),
            ToolbarItemPlacement("quantity_field", 0, 4),
            ToolbarItemPlacement("action_field", 0, 5),
        ),
        (0, 1, 0, 0, 0, 0),
    ),
}


def normalize_toolbar_mode(mode: str | None) -> str:
    value = str(mode or "wide").strip().lower()
    if value in {"stacked", "narrow", "regular"}:
        return "compact"
    return value if value in TOOLBAR_MODES else "wide"


def resolve_toolbar_mode(
    *,
    width: int,
    stacked_breakpoint: int | None = None,
    compact_breakpoint: int | None = None,
    wide_required_width: int | None = None,
    compact_required_width: int | None = None,
) -> str:
    current = max(0, int(width or 0))
    if wide_required_width is not None and compact_required_width is not None:
        return resolve_fluid_toolbar_mode(
            width=current,
            wide_required_width=int(wide_required_width),
            compact_required_width=int(compact_required_width),
        )
    if (
        stacked_breakpoint is not None
        and current
        and (current < int(stacked_breakpoint))
    ):
        return "compact"
    if (
        compact_breakpoint is not None
        and current
        and (current < int(compact_breakpoint))
    ):
        return "compact"
    return "wide"


def toolbar_layout_spec(mode: str | None) -> ToolbarLayoutSpec:
    return _LAYOUTS[normalize_toolbar_mode(mode)]


def find_selected_branch_index(
    *, items: Iterable[tuple[str, str]] | None, selected_data: str
) -> int:
    wanted = str(selected_data or "").strip()
    if not wanted:
        return -1
    for index, (_label, value) in enumerate(items or ()):
        if str(value or "").strip() == wanted:
            return index
    return -1
