from __future__ import annotations
from dataclasses import dataclass
import logging
import os
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication, QWidget
from runtime.shared.objects import call_if_callable
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS, UI_OPERATION_EXCEPTIONS

logger = logging.getLogger(__name__)


def layout_mode_for_width(width: int | None) -> str:
    resolved = max(0, int(width or 0))
    if resolved < 768:
        return "compact"
    if resolved < 1200:
        return "regular"
    return "wide"


@dataclass(frozen=True, slots=True)
class ResponsiveProfile:
    name: str
    width: int
    height: int
    orientation: str
    density: str
    navigation_mode: str
    touch_mode: bool
    control_height: int
    touch_target: int
    page_margin: int
    gap: int
    dialog_margin: int
    visual_breakpoint: str = "generic"

    @property
    def is_narrow(self) -> bool:
        return self.name in {"tablet_portrait", "compact"}

    @property
    def is_tablet(self) -> bool:
        return self.name in {"tablet_portrait", "tablet_landscape"}

    @property
    def supports_inline_entry_row(self) -> bool:
        return True

    @property
    def supports_split_admin_workspace(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class ScreenDeviceProfile:
    """Describe the active screen/monitor used for adaptive layout decisions."""

    name: str
    width: int
    height: int
    available_width: int
    available_height: int
    logical_dpi: float
    device_pixel_ratio: float
    orientation: str
    visual_breakpoint: str

    @property
    def signature(self) -> str:
        """Return a stable readable signature for diagnostics and UI properties."""
        return f"{self.name}:{self.available_width}x{self.available_height}@{self.logical_dpi:.0f}dpi/{self.device_pixel_ratio:.2f}x"


def _screen_for_anchor(anchor=None, app: QApplication | None = None):
    """Return the Qt screen containing an anchor point, with robust fallback."""
    app = app or QApplication.instance()
    if app is None:
        return None
    try:
        if anchor is not None and hasattr(app, "screenAt"):
            screen = app.screenAt(anchor)
            if screen is not None:
                return screen
        return app.primaryScreen()
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("screen lookup fallback failed", exc_info=True)
        return app.primaryScreen() if app is not None else None


def screen_for_widget(widget: QWidget | None = None, app: QApplication | None = None):
    """Return the current screen for a widget/window instead of assuming a brand or model."""
    anchor = None
    try:
        if widget is not None and hasattr(widget, "frameGeometry"):
            anchor = widget.frameGeometry().center()
    except SERVICE_OPERATION_EXCEPTIONS:
        anchor = None
    return _screen_for_anchor(anchor, app)


def screen_device_profile(
    widget: QWidget | None = None,
    *,
    app: QApplication | None = None,
    width: int | None = None,
    height: int | None = None,
) -> ScreenDeviceProfile:
    """Detect the active screen geometry, DPI, scale, and adaptive breakpoint."""
    app = app or QApplication.instance()
    screen = screen_for_widget(widget, app)
    available = screen.availableGeometry() if screen is not None else None
    geometry = screen.geometry() if screen is not None else None
    available_width = int(
        width or (available.width() if available is not None else 1280)
    )
    available_height = int(
        height or (available.height() if available is not None else 800)
    )
    full_width = int(geometry.width() if geometry is not None else available_width)
    full_height = int(geometry.height() if geometry is not None else available_height)
    try:
        logical_dpi = float(screen.logicalDotsPerInch()) if screen is not None else 96.0
    except SERVICE_OPERATION_EXCEPTIONS:
        logical_dpi = 96.0
    try:
        ratio = float(screen.devicePixelRatio()) if screen is not None else 1.0
    except SERVICE_OPERATION_EXCEPTIONS:
        ratio = 1.0
    try:
        name = str(screen.name() or "screen") if screen is not None else "screen"
    except SERVICE_OPERATION_EXCEPTIONS:
        name = "screen"
    orientation = "portrait" if available_height > available_width else "landscape"
    breakpoint = visual_breakpoint_for_dimensions(available_width, available_height)
    return ScreenDeviceProfile(
        name=name,
        width=max(320, full_width),
        height=max(240, full_height),
        available_width=max(320, available_width),
        available_height=max(240, available_height),
        logical_dpi=logical_dpi,
        device_pixel_ratio=max(0.75, min(4.0, ratio)),
        orientation=orientation,
        visual_breakpoint=breakpoint,
    )


def apply_screen_device_properties(
    widget: QWidget | None, profile: ScreenDeviceProfile
) -> None:
    """Expose detected device/screen facts as Qt dynamic properties for QSS and QA."""
    if widget is None:
        return
    for name, value in {
        "screenName": profile.name,
        "screenSignature": profile.signature,
        "screenWidth": profile.available_width,
        "screenHeight": profile.available_height,
        "screenDpi": round(profile.logical_dpi, 2),
        "screenScale": round(profile.device_pixel_ratio, 2),
        "screenOrientation": profile.orientation,
        "visualBreakpoint": profile.visual_breakpoint,
        "deviceAdaptiveContract": "auto-detect-current-screen-dpi-size-any-device",
    }.items():
        widget.setProperty(name, value)


def _available_size(app: QApplication | None = None) -> QSize:
    detected = screen_device_profile(app=app)
    return QSize(detected.available_width, detected.available_height)


def _touch_requested() -> bool:
    return str(os.environ.get("HERFY_TOUCH_MODE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def visual_breakpoint_for_dimensions(width: int, height: int) -> str:
    """Return the adaptive visual breakpoint for any desktop screen size.

    The rules are not tied to a brand, panel vendor, or one laptop model. They
    use the real available width and height so the same build can run across
    mixed fleets: small POS terminals, 720p/768p laptops, FHD desktops, QHD,
    and 4K displays.  The named 1280x720, 1366x768, and 1920x1080 breakpoints
    remain explicit QA targets, but the surrounding tiers keep the UI adaptive
    for the rest of the 400-device fleet.
    """
    resolved_width = int(width or 0)
    resolved_height = int(height or 0)
    shortest = min(resolved_width, resolved_height)
    longest = max(resolved_width, resolved_height)
    if longest <= 1024 or shortest <= 600:
        return "small_terminal"
    if resolved_width <= 1280 or resolved_height <= 720:
        return "hd_720"
    if resolved_width <= 1366 or resolved_height <= 768:
        return "laptop_768"
    if resolved_width <= 1440 or resolved_height <= 900:
        return "hd_plus_900"
    if resolved_width <= 1920 or resolved_height <= 1080:
        return "fhd_1080"
    if resolved_width <= 2560 or resolved_height <= 1440:
        return "qhd_1440"
    if resolved_width <= 3840 or resolved_height <= 2160:
        return "uhd_2160"
    return "large_desktop"


def fluid_content_width(widget: QWidget | None = None, *, fallback: int = 1024) -> int:
    """Return the live content width available to a widget.

    This intentionally avoids brand/model/screen-size assumptions.  It uses the
    current widget viewport/contents rectangle first, then falls back to the
    supplied value.  The same rule works for resized windows, maximized windows,
    QScrollArea-hosted pages, and mixed-monitor setups.
    """
    if widget is None:
        return max(1, int(fallback or 1))
    try:
        viewport = getattr(widget, "viewport", None)
        if callable(viewport):
            vp = call_if_callable(viewport)
            if vp is not None and int(vp.width() or 0) > 0:
                return max(1, int(vp.width()))
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("fluid_content_width viewport lookup failed", exc_info=True)
    try:
        rect = widget.contentsRect()
        if int(rect.width() or 0) > 0:
            return max(1, int(rect.width()))
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("fluid_content_width contents lookup failed", exc_info=True)
    try:
        if int(widget.width() or 0) > 0:
            return max(1, int(widget.width()))
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("fluid_content_width width lookup failed", exc_info=True)
    return max(1, int(fallback or 1))


def fluid_columns_for_width(
    width: int | None,
    *,
    item_count: int,
    min_item_width: int,
    gap: int = 12,
    min_columns: int = 1,
    max_columns: int | None = None,
) -> int:
    """Calculate responsive grid columns from real available width.

    The grid is content-first: cards wrap when their minimum readable width no
    longer fits.  This is more robust than a list of fixed device breakpoints and
    works across a fleet of different laptop/POS/desktop displays.
    """
    count = max(1, int(item_count or 1))
    lower = max(1, int(min_columns or 1))
    upper = min(count, max(lower, int(max_columns or count)))
    available = max(1, int(width or 1))
    item_min = max(1, int(min_item_width or 1))
    spacing = max(0, int(gap or 0))
    for columns in range(upper, lower - 1, -1):
        required = columns * item_min + max(0, columns - 1) * spacing
        if required <= available:
            return columns
    return lower


def resolve_fluid_toolbar_mode(
    *, width: int | None, wide_required_width: int, compact_required_width: int
) -> str:
    """Resolve toolbar mode from measured required widths, not screen names."""
    available = max(1, int(width or 1))
    if available >= max(1, int(wide_required_width or 1)):
        return "wide"
    if available >= max(1, int(compact_required_width or 1)):
        return "compact"
    return "compact"


def profile_for_dimensions(
    width: int | None = None,
    height: int | None = None,
    *,
    app: QApplication | None = None,
) -> ResponsiveProfile:
    detected = screen_device_profile(app=app, width=width, height=height)
    resolved_width = max(320, int(width or detected.available_width))
    resolved_height = max(360, int(height or detected.available_height))
    orientation = "portrait" if resolved_height > resolved_width else "landscape"
    visual_breakpoint = visual_breakpoint_for_dimensions(
        resolved_width, resolved_height
    )
    if resolved_width < 760:
        name = "compact"
    elif orientation == "portrait" and resolved_width < 940:
        name = "tablet_portrait"
    elif resolved_width < 1080:
        name = "tablet_landscape"
    elif resolved_width < 1760:
        name = "desktop"
    else:
        name = "wide"
    touch_mode = _touch_requested()
    if name == "compact":
        return ResponsiveProfile(
            name,
            resolved_width,
            resolved_height,
            orientation,
            "dense",
            "compact_sidebar",
            _touch_requested(),
            21,
            24,
            2,
            2,
            5,
            visual_breakpoint,
        )
    if name == "tablet_portrait":
        return ResponsiveProfile(
            name,
            resolved_width,
            resolved_height,
            orientation,
            "comfortable",
            "compact_sidebar",
            _touch_requested(),
            22,
            25,
            3,
            3,
            6,
            visual_breakpoint,
        )
    if name == "tablet_landscape":
        return ResponsiveProfile(
            name,
            resolved_width,
            resolved_height,
            orientation,
            "comfortable" if touch_mode else "regular",
            "sidebar",
            touch_mode,
            24 if touch_mode else 23,
            28 if touch_mode else 26,
            4,
            4,
            7,
            visual_breakpoint,
        )
    if name == "desktop":
        return ResponsiveProfile(
            name,
            resolved_width,
            resolved_height,
            orientation,
            "regular",
            "sidebar",
            touch_mode,
            23 if visual_breakpoint == "laptop_768" else 24,
            26 if visual_breakpoint == "laptop_768" else 27,
            5,
            5,
            8,
            visual_breakpoint,
        )
    return ResponsiveProfile(
        name,
        resolved_width,
        resolved_height,
        orientation,
        "regular",
        "sidebar",
        touch_mode,
        25,
        28,
        7,
        6,
        10,
        visual_breakpoint,
    )


def profile_for_widget(
    widget: QWidget | None, *, app: QApplication | None = None
) -> ResponsiveProfile:
    width = int(widget.width()) if widget is not None and widget.width() > 0 else None
    height = (
        int(widget.height()) if widget is not None and widget.height() > 0 else None
    )
    return profile_for_dimensions(width, height, app=app)


def apply_profile_properties(
    widget: QWidget | None, profile: ResponsiveProfile
) -> None:
    if widget is None:
        return
    properties = {
        "responsiveProfile": profile.name,
        "layoutMode": layout_mode_for_width(profile.width),
        "deviceClass": (
            "compact"
            if profile.is_narrow
            else "comfortable" if profile.is_tablet else "expanded"
        ),
        "density": profile.density,
        "touchUi": profile.touch_mode,
        "portraitUi": profile.orientation == "portrait",
        "navigationMode": profile.navigation_mode,
        "visualBreakpoint": profile.visual_breakpoint,
        "heightConstrainedUi": profile.visual_breakpoint
        in {"small_terminal", "hd_720", "laptop_768"},
        "deviceAdaptiveContract": "auto-detect-current-screen-dpi-size-any-device",
        "compactUi": profile.is_narrow,
        "tabletUi": profile.is_tablet,
        "expandedUi": profile.name in {"desktop", "wide"},
    }
    for name, value in properties.items():
        widget.setProperty(name, value)
