from __future__ import annotations
"""Shared adaptive resize helpers for Qt widgets.

The module centralizes HerfyClient responsive behavior so individual pages do
avoid repeated full layout work on every resize pixel. Widgets schedule a debounced reflow;
the reflow runs only when the semantic layout mode changes.
"""

import logging
from dataclasses import dataclass
from inspect import Parameter, signature
from collections.abc import Callable
from typing import Any
from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS

logger = logging.getLogger(__name__)
COMPACT_MAX_WIDTH = 768
WIDE_MIN_WIDTH = 1200
LAYOUT_MODE_COMPACT = "compact"
LAYOUT_MODE_REGULAR = "regular"
LAYOUT_MODE_WIDE = "wide"
LAYOUT_MODES = frozenset({LAYOUT_MODE_COMPACT, LAYOUT_MODE_REGULAR, LAYOUT_MODE_WIDE})


@dataclass(frozen=True, slots=True)
class LayoutModeState:
    """Resolved adaptive layout state for a widget."""

    mode: str
    width: int
    height: int
    profile: Any

    @property
    def is_compact(self) -> bool:
        """Return true when the UI should minimize horizontal chrome."""
        return self.mode == LAYOUT_MODE_COMPACT

    @property
    def is_regular(self) -> bool:
        """Return true for the middle/default desktop layout."""
        return self.mode == LAYOUT_MODE_REGULAR

    @property
    def is_wide(self) -> bool:
        """Return true when a wide multi-column layout is safe."""
        return self.mode == LAYOUT_MODE_WIDE


def layout_mode_for_width(width: int | None) -> str:
    """Resolve HerfyClient semantic layout mode from the available width."""
    resolved = max(0, int(width or 0))
    if resolved < COMPACT_MAX_WIDTH:
        return LAYOUT_MODE_COMPACT
    if resolved < WIDE_MIN_WIDTH:
        return LAYOUT_MODE_REGULAR
    return LAYOUT_MODE_WIDE


def viewport_size(
    widget: QWidget | None, *, fallback_width: int = 1024
) -> tuple[int, int]:
    """Return the best live size for a widget or scroll-area viewport."""
    if widget is None:
        return (max(1, int(fallback_width or 1)), 1)
    try:
        viewport = getattr(widget, "viewport", None)
        if callable(viewport):
            area = viewport()
            if area is not None and int(area.width() or 0) > 0:
                return (max(1, int(area.width())), max(1, int(area.height() or 1)))
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Unable to resolve viewport size", exc_info=True)
    try:
        rect = widget.contentsRect()
        if int(rect.width() or 0) > 0:
            return (max(1, int(rect.width())), max(1, int(rect.height() or 1)))
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Unable to resolve widget contents size", exc_info=True)
    try:
        return (
            max(1, int(widget.width() or fallback_width)),
            max(1, int(widget.height() or 1)),
        )
    except UI_OPERATION_EXCEPTIONS:
        return (max(1, int(fallback_width or 1)), 1)


def _profile_for_size(width: int, height: int):
    """Create a ResponsiveProfile without importing layout at module import time."""
    from runtime.presentation.layout.profiles import profile_for_dimensions

    return profile_for_dimensions(width, height, app=QApplication.instance())


def layout_state_for_widget(widget: QWidget | None) -> LayoutModeState:
    """Resolve the complete adaptive layout state for a widget."""
    width, height = viewport_size(widget)
    return LayoutModeState(
        mode=layout_mode_for_width(width),
        width=width,
        height=height,
        profile=_profile_for_size(width, height),
    )


class LayoutModeController(QObject):
    """Debounced mode controller that emits only on semantic mode changes."""

    modeChanged = pyqtSignal(str, object)
    reflowRequested = pyqtSignal(str, object)

    def __init__(self, owner: QWidget, *, interval_ms: int = 60) -> None:
        super().__init__(owner)
        self._owner = owner
        self._current_mode = ""
        self._pending_force = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(0, int(interval_ms or 0)))
        self._timer.timeout.connect(self._flush)

    @property
    def current_mode(self) -> str:
        """Return the last emitted layout mode."""
        return self._current_mode

    def schedule(self, *, force: bool = False) -> None:
        """Schedule a debounced reflow evaluation."""
        self._pending_force = bool(force or self._pending_force)
        self._timer.start()

    def flush_now(self, *, force: bool = False) -> None:
        """Evaluate the layout mode immediately."""
        self._pending_force = bool(force or self._pending_force)
        self._flush()

    def _flush(self) -> None:
        owner = self._owner
        if owner is None:
            return
        state = layout_state_for_widget(owner)
        old_mode = self._current_mode
        changed = state.mode != old_mode
        if changed:
            self._current_mode = state.mode
            self.modeChanged.emit(state.mode, state.profile)
        if changed or self._pending_force:
            self.reflowRequested.emit(state.mode, state.profile)
        self._pending_force = False


def ensure_layout_mode_controller(
    owner: QWidget, *, attr_name: str = "_layout_mode_controller", interval_ms: int = 60
) -> LayoutModeController:
    """Create or return the owner's shared debounced layout controller."""
    controller = getattr(owner, attr_name, None)
    if isinstance(controller, LayoutModeController):
        return controller
    controller = LayoutModeController(owner, interval_ms=interval_ms)
    setattr(owner, attr_name, controller)
    return controller


def _call_with_supported_args(
    callback: Callable[..., Any], *, mode: str, profile: Any, force: bool = False
) -> Any:
    """Call a callback with only the keyword arguments it declares."""
    try:
        params = signature(callback).parameters
    except (TypeError, ValueError):
        return callback()
    kwargs: dict[str, Any] = {}
    accepts_var_kw = any(
        (param.kind == Parameter.VAR_KEYWORD for param in params.values())
    )
    if accepts_var_kw or "mode" in params:
        kwargs["mode"] = mode
    if accepts_var_kw or "profile" in params:
        kwargs["profile"] = profile
    if accepts_var_kw or "force" in params:
        kwargs["force"] = force
    return callback(**kwargs)


def dispatch_reflow_callback(
    owner: Any, callback_name: str, *, mode: str, profile: Any, force: bool = False
) -> None:
    """Invoke an owner's reflow callback with a safe adaptive signature."""
    callback = getattr(owner, str(callback_name or ""), None)
    if callable(callback):
        _call_with_supported_args(callback, mode=mode, profile=profile, force=force)


class DebouncedResizeMixin:
    """Mixin for QWidget subclasses that reflow only when layout mode changes."""

    responsive_reflow_method = "apply_responsive_profile"
    responsive_resize_interval_ms = 60

    def _ensure_adaptive_resize_controller(self) -> LayoutModeController:
        controller = ensure_layout_mode_controller(
            self, interval_ms=int(getattr(self, "responsive_resize_interval_ms", 60))
        )
        if not bool(getattr(self, "_adaptive_resize_connected", False)):
            controller.reflowRequested.connect(self._on_adaptive_reflow_requested)
            self._adaptive_resize_connected = True
        return controller

    def _schedule_adaptive_reflow(self, *, force: bool = False) -> None:
        self._ensure_adaptive_resize_controller().schedule(force=force)

    def _on_adaptive_reflow_requested(self, mode: str, profile: Any) -> None:
        dispatch_reflow_callback(
            self,
            str(getattr(self, "responsive_reflow_method", "apply_responsive_profile")),
            mode=mode,
            profile=profile,
            force=True,
        )

    def resizeEvent(self, event):
        """Debounce QWidget resize events before any expensive reflow."""
        super().resizeEvent(event)
        self._schedule_adaptive_reflow()

    def showEvent(self, event):
        """Force the first reflow once the widget has a real size."""
        super().showEvent(event)
        self._schedule_adaptive_reflow(force=True)
