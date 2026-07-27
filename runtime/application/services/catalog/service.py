from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.booleans import parse_bool
from runtime.domain.access import PermissionContext, PermissionService

EXPIRY_DATE_FIELD_ALIASES = (
    "expiry_date",
    "expiration_date",
    "exp_date",
    "expiryDate",
    "expirationDate",
    "expiry",
)


@dataclass(frozen=True)
class HomeDashboardStats:
    branches: int
    tracked: int
    expiring: int
    expired: int
    usage: int
    stored: int

    def as_dict(self) -> dict[str, int]:
        return {
            "branches": int(self.branches),
            "tracked": int(self.tracked),
            "expiring": int(self.expiring),
            "expired": int(self.expired),
            "usage": int(self.usage),
            "stored": int(self.stored),
        }


@dataclass(frozen=True)
class HomeDashboardSnapshot:
    ctx: PermissionContext
    profile: Any
    is_ar: bool
    username: str
    role_txt: str
    allowed: tuple[str, ...]
    active_branch: str
    values: HomeDashboardStats
    can_manage_org: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "ctx": self.ctx,
            "profile": self.profile,
            "is_ar": self.is_ar,
            "username": self.username,
            "role_txt": self.role_txt,
            "allowed": list(self.allowed),
            "active_branch": self.active_branch,
            "values": self.values.as_dict(),
            "can_manage_org": bool(self.can_manage_org),
        }


class HomeDashboardService:

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    def _safe_int_setting(self, key: str, default: int) -> int:
        try:
            return int(self._db.get_setting(key, str(default)))
        except SERVICE_OPERATION_EXCEPTIONS:
            return int(default)
        except (TypeError, ValueError):
            return int(default)

    def _allowed_branches(self, ctx: PermissionContext) -> list[str]:
        return [
            str(branch).strip()
            for branch in self._db.allowed_branches() or ctx.scope.branches or []
            if str(branch).strip()
        ]

    def _safe_fetch_tracking_rows(
        self, ctx: PermissionContext, allowed: list[str]
    ) -> list[dict]:
        branch_hint = (
            "all"
            if ctx.scope.all_branches or len(allowed) != 1
            else self._db.get_active_branch() or (allowed[0] if allowed else "")
        )
        try:
            rows = self._db.fetch_tracked_products(branch_filter_override=branch_hint)
        except SERVICE_OPERATION_EXCEPTIONS:
            rows = []
        if not isinstance(rows, list):
            rows = []
        if allowed and (not ctx.scope.all_branches):
            allowed_set = {branch.lower() for branch in allowed}
            rows = [
                row
                for row in rows
                if not str((row or {}).get("branch", "") or "").strip()
                or str((row or {}).get("branch", "") or "").strip().lower()
                in allowed_set
            ]
        return rows

    def _safe_fetch_rows(self, fetcher: Callable[[], Any]) -> list[dict]:
        try:
            rows = fetcher()
        except SERVICE_OPERATION_EXCEPTIONS:
            rows = []
        return rows if isinstance(rows, list) else []

    def _safe_fetch_usage_rows(self) -> list[dict]:
        return self._safe_fetch_rows(self._db.fetch_usage_products)

    def _safe_fetch_stored_rows(self) -> list[dict]:
        return self._safe_fetch_rows(self._db.fetch_stored_products)

    def _active_branch(
        self, *, allowed: list[str], ctx: PermissionContext, view_branch: str | None
    ) -> str:
        active_branch = str(
            view_branch
            if view_branch is not None
            else self._db.get_active_branch() or ctx.active_branch or ""
        ).strip()
        if not active_branch or active_branch.lower() == "all":
            active_branch = allowed[0] if len(allowed) == 1 else ""
        return active_branch

    def _expiry_counters(self, rows: list[dict]) -> tuple[int, int]:
        warn = max(3, self._safe_int_setting("expiry_expiring_soon_threshold_days", 7))
        recent_exp = 0
        expiring_count = 0
        expired_recent_count = 0
        for row in rows:
            exp_date = str((row or {}).get("expiry_date", "") or "").strip()
            if not exp_date:
                continue
            try:
                expiry_date = datetime.strptime(exp_date, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            delta = (expiry_date - date.today()).days
            if 0 <= delta <= warn:
                expiring_count += 1
            elif delta < 0 and abs(delta) <= recent_exp:
                expired_recent_count += 1
        return (expiring_count, expired_recent_count)

    def _safe_can_manage_org(self) -> bool:
        try:
            return bool(self._db.can_manage_org())
        except SERVICE_OPERATION_EXCEPTIONS:
            return False

    def build_snapshot(
        self,
        *,
        profile: Any = None,
        permission_context: PermissionContext | None = None,
        view_branch: str | None = None,
        is_ar: bool = False,
    ) -> HomeDashboardSnapshot:
        ctx = permission_context or self._db.perm_ctx()
        username = str(getattr(profile, "username", "") or ctx.username or "").strip()
        role_txt = PermissionService.role_label(
            permission_context=ctx, language="ar" if is_ar else "en"
        )
        allowed = self._allowed_branches(ctx)
        active_branch = self._active_branch(
            allowed=allowed, ctx=ctx, view_branch=view_branch
        )
        tracked_rows = self._safe_fetch_tracking_rows(ctx, allowed)
        usage_rows = self._safe_fetch_usage_rows()
        stored_rows = self._safe_fetch_stored_rows()
        expiring_count, expired_recent_count = self._expiry_counters(tracked_rows)
        return HomeDashboardSnapshot(
            ctx=ctx,
            profile=profile,
            is_ar=bool(is_ar),
            username=username,
            role_txt=role_txt,
            allowed=tuple(allowed),
            active_branch=active_branch,
            values=HomeDashboardStats(
                branches=len(allowed),
                tracked=len(tracked_rows),
                expiring=expiring_count,
                expired=expired_recent_count,
                usage=len(usage_rows),
                stored=len(stored_rows),
            ),
            can_manage_org=self._safe_can_manage_org(),
        )


from runtime.shared.settings.config import _
from runtime.shared.strings import clean_text as _text

TRACKING_EMPTY_MESSAGE = _(
    "No tracked products yet. Select a branch and save a product to start monitoring."
)
USAGE_EMPTY_MESSAGE = _(
    "No usage rows to show. Load files or adjust filters to calculate usage."
)
EXPIRY_DATE_FIELD_ALIASES = (
    "expiry_date",
    "expiration_date",
    "exp_date",
    "expiryDate",
    "expirationDate",
    "expiry",
)


@dataclass(frozen=True)
class PageVisibleState:
    status_text: str
    status_role: str
    empty_message: str
    empty_visible: bool


def _total(value: int) -> int:
    return max(0, int(value or 0))


def _visible_message_state(
    *, total: int, message: str, role: str, default_empty_message: str
) -> PageVisibleState:
    return PageVisibleState(
        message, role, message if total == 0 else default_empty_message, total == 0
    )


class PageVisibleStateService:

    @staticmethod
    def tracking_state(
        *,
        total: int,
        loading: bool = False,
        truncated: bool = False,
        error_message: str = "",
    ) -> PageVisibleState:
        total = _total(total)
        if loading:
            return PageVisibleState(
                _("Loading..."), "muted", TRACKING_EMPTY_MESSAGE, False
            )
        message = _text(error_message)
        if message:
            return _visible_message_state(
                total=total,
                message=message,
                role="error",
                default_empty_message=TRACKING_EMPTY_MESSAGE,
            )
        if truncated:
            return PageVisibleState(
                _("Showing first items only. Refine filters for a smaller result set."),
                "warning",
                TRACKING_EMPTY_MESSAGE,
                total == 0,
            )
        return PageVisibleState("", "muted", TRACKING_EMPTY_MESSAGE, total == 0)

    @staticmethod
    def usage_state(
        *,
        total: int,
        loading: bool = False,
        status_text: str = "",
        error_message: str = "",
        access_allowed: bool = True,
        access_reason: str = "",
    ) -> PageVisibleState:
        total = _total(total)
        if loading:
            return PageVisibleState(
                _text(status_text) or _("Calculating..."),
                "muted",
                USAGE_EMPTY_MESSAGE,
                False,
            )
        if not access_allowed:
            return _visible_message_state(
                total=total,
                message=_text(access_reason)
                or _("Usage is not available for the current account."),
                role="warning",
                default_empty_message=USAGE_EMPTY_MESSAGE,
            )
        message = _text(error_message)
        if message:
            return _visible_message_state(
                total=total,
                message=message,
                role="error",
                default_empty_message=USAGE_EMPTY_MESSAGE,
            )
        status = _text(status_text)
        if total == 0 and status:
            return PageVisibleState(status, "warning", status, True)
        return PageVisibleState(status, "muted", USAGE_EMPTY_MESSAGE, total == 0)


from collections.abc import Mapping
from runtime.shared.objects import normalize_int, safe_get

EXPIRY_DATE_FIELD_ALIASES = (
    "expiry_date",
    "expiration_date",
    "exp_date",
    "expiryDate",
    "expirationDate",
    "expiry",
)


def stored_product_label(row: Mapping[str, Any] | None) -> str:
    data = row or {}
    return f"{safe_get(data, 'material_number', '')} - {safe_get(data, 'name', '')}"


def validate_stored_product_input(material_number: str, name: str) -> str:
    if not str(material_number or "").strip() or not str(name or "").strip():
        return _("Material number and material name are required.")
    return ""


def usage_product_label(row: Mapping[str, Any] | None) -> str:
    data = row or {}
    label = f"{safe_get(data, 'material', '')} - {safe_get(data, 'name', '')}"
    unit = str(safe_get(data, "uom", "") or "").strip()
    if unit:
        label += f" ({unit})"
    return label


def find_usage_selected_row(
    rows: list[Mapping[str, Any]] | None, selected_material: str
) -> int | None:
    selected = str(selected_material or "").strip()
    if not selected:
        return None
    for index, row in enumerate(rows or []):
        if str(safe_get(row, "material", "") or "").strip() == selected:
            return index
    return None


def usage_reload_status(*, pending: int, current_text: str) -> str:
    if int(pending or 0) > 0:
        return _("Offline changes pending sync") + f": {int(pending or 0)}"
    stripped = str(current_text or "").strip()
    if not stripped or stripped == _("Loading..."):
        return ""
    return stripped


def validate_usage_product_input(material: str, name: str) -> str:
    if not str(material or "").strip():
        return _("Material number is required.")
    if not str(name or "").strip():
        return _("Material name is required.")
    return ""


def queued_status_message(*, action: str, queued: bool) -> str:
    action_name = str(action or "").strip().lower()
    if action_name == "save":
        return (
            _("Saved locally. Will sync when connection returns.")
            if queued
            else _("Saved.")
        )
    if action_name == "delete":
        return (
            _("Deleted locally. Will sync when connection returns.")
            if queued
            else _("Deleted.")
        )
    if action_name == "refresh":
        return _("Consumption item catalog refreshed.")
    return ""



EXPIRY_DATE_FIELD_ALIASES = (
    "expiry_date",
    "expiration_date",
    "exp_date",
    "expiryDate",
    "expirationDate",
    "expiry",
)


@dataclass(frozen=True)
class HomeDashboardViewState:
    is_ar: bool
    page_title: str
    greeting: str
    subtitle: str
    branches_title: str
    branches_subtitle: str
    actions_title: str
    actions_subtitle: str
    track_text: str
    usage_text: str
    admin_text: str
    stat_labels: dict[str, str]
    top_chips: tuple[str, ...]
    empty_branches_text: str
    can_open_tracking: bool
    can_open_usage: bool
    can_open_admin: bool


class HomeDashboardPresenter:

    @classmethod
    def build_from_payload(cls, payload: Mapping[str, Any]) -> HomeDashboardViewState:
        values = dict(payload.get("values") or {})
        snapshot = HomeDashboardSnapshot(
            ctx=payload.get("ctx"),
            profile=payload.get("profile"),
            is_ar=parse_bool(payload.get("is_ar"), False),
            username=str(payload.get("username") or "").strip(),
            role_txt=str(payload.get("role_txt") or "").strip(),
            allowed=tuple(
                (
                    str(branch).strip()
                    for branch in payload.get("allowed") or []
                    if str(branch).strip()
                )
            ),
            active_branch=str(payload.get("active_branch") or "").strip(),
            values=HomeDashboardStats(
                branches=normalize_int(values.get("branches"), 0),
                tracked=normalize_int(values.get("tracked"), 0),
                expiring=normalize_int(values.get("expiring"), 0),
                expired=normalize_int(values.get("expired"), 0),
                usage=normalize_int(values.get("usage"), 0),
                stored=normalize_int(values.get("stored"), 0),
            ),
            can_manage_org=parse_bool(payload.get("can_manage_org"), False),
        )
        return cls.build(snapshot)

    @staticmethod
    def build(snapshot: HomeDashboardSnapshot) -> HomeDashboardViewState:
        ctx = snapshot.ctx
        is_ar = bool(snapshot.is_ar)
        username = str(snapshot.username or "").strip()
        role_txt = str(snapshot.role_txt or "").strip()
        active_branch = str(snapshot.active_branch or "").strip()
        top_chips = tuple(
            (
                text
                for text in (
                    _("Role: {role}").format(role=role_txt) if role_txt else "",
                    (
                        _("Operating area: {area}").format(area=ctx.area_id)
                        if str(ctx.area_id or "").strip()
                        else ""
                    ),
                    (
                        _("Active restaurant branch: {branch}").format(
                            branch=active_branch
                        )
                        if active_branch
                        else ""
                    ),
                )
                if text
            )
        )
        stat_labels = {
            "branches": _("Authorized branches"),
            "tracked": _("Tracked items"),
            "expiring": _("Expiring soon"),
            "expired": _("Recently expired"),
            "usage": _("Usage products"),
            "stored": _("Stored products"),
        }
        return HomeDashboardViewState(
            is_ar=is_ar,
            page_title=_("Dashboard"),
            greeting=(
                _("Welcome, {username}").format(username=username)
                if username
                else _("Welcome")
            ),
            subtitle=_("Overview of branches, products, and tracking status."),
            branches_title=_("Branches"),
            branches_subtitle="",
            actions_title=_("Actions"),
            actions_subtitle="",
            track_text=_("Open tracking"),
            usage_text=_("Open usage"),
            admin_text=_("Admin Dashboard"),
            stat_labels=stat_labels,
            top_chips=top_chips,
            empty_branches_text=_("No authorized restaurant branches"),
            can_open_tracking=bool(snapshot.allowed),
            can_open_usage=bool(snapshot.allowed),
            can_open_admin=bool(snapshot.can_manage_org),
        )
