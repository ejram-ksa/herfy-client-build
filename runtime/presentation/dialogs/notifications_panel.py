from __future__ import annotations
from runtime.presentation.widgets import repolish_widget_tree
from runtime.presentation.widgets import clear_layout, set_tab_order
from PyQt5.QtWidgets import QAbstractScrollArea, QListWidget
from runtime.shared.booleans import parse_bool
import logging
from dataclasses import dataclass as _dataclass
from typing import Any
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)
from runtime.shared.settings.config import _
from runtime.application.services.translations import is_rtl, normalize_language_code
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS, UI_OPERATION_EXCEPTIONS
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.helpers import add_stretch
from runtime.presentation.widgets import (
    direction_for_rtl,
    leading_alignment,
    set_accessibility,
    trailing_alignment,
)

logger = logging.getLogger(__name__)


@_dataclass(frozen=True)
class PopupGeometry:
    width: int
    height: int
    x: int
    y: int


@_dataclass(frozen=True)
class NotificationViewItem:
    index: int
    title: str
    timestamp: str
    product: str
    material_number: str
    status: str
    qty: str
    branch: str
    days_text: str
    expiry_date: str
    message: str
    read: bool
    level: str


class NotificationsPresenter:

    def __init__(self, db_manager: Any = None) -> None:
        self._db: Any = db_manager

    def language(self) -> str:
        try:
            if self._db is None:
                return "ar"
            return normalize_language_code(
                str(self._db.get_setting("language", "ar") or "ar")
            )
        except SERVICE_OPERATION_EXCEPTIONS:
            return "ar"

    def is_rtl(self) -> bool:
        return is_rtl(self.language())

    def summary_text(self, items: list[dict]) -> str:
        unread = sum(
            (1 for item in items if not parse_bool((item or {}).get("read"), False))
        )
        return f"{_('Unread')}: {unread} / {len(items)}"

    def to_view_items(self, notifications: list[dict]) -> list[NotificationViewItem]:
        return [
            self._to_view_item(index, raw)
            for index, raw in enumerate(notifications or [])
        ]

    def _to_view_item(self, index: int, raw: Any) -> NotificationViewItem:
        entry = raw if isinstance(raw, dict) else {"message": str(raw)}
        return NotificationViewItem(
            index=index,
            title=str(entry.get("title") or _("Notification")),
            timestamp=str(entry.get("timestamp") or ""),
            product=str(
                entry.get("product")
                or entry.get("product_name")
                or entry.get("display_product")
                or ""
            ).strip(),
            material_number=str(entry.get("material_number") or "").strip(),
            status=str(entry.get("status") or entry.get("status_label") or "").strip(),
            qty=str(entry.get("qty") or "").strip(),
            branch=str(entry.get("branch") or "").strip(),
            days_text=str(entry.get("days_text") or "").strip(),
            expiry_date=str(entry.get("expiry_date") or "").strip(),
            message=str(entry.get("message") or "").strip(),
            read=parse_bool(entry.get("read"), False),
            level=str(
                entry.get("level") or entry.get("severity") or entry.get("status") or ""
            ).lower(),
        )

    def detail_lines(self, item: NotificationViewItem) -> list[str]:
        fields = [
            ("", item.message),
            (_("Restaurant branch"), item.branch),
            (_("Material number"), item.material_number),
            (_("On-hand quantity"), item.qty),
            (_("Days Remaining"), item.days_text),
            (_("Expiry Date"), item.expiry_date),
        ]
        return [
            value if not label else f"{label}: {value}"
            for label, value in fields
            if value
        ]

    def popup_geometry(
        self,
        *,
        parent_width: int,
        parent_height: int,
        anchor_x: int,
        anchor_y: int,
        anchor_width: int,
        anchor_height: int,
        min_width: int,
        max_width: int,
        preferred_height: int,
        item_count: int,
    ) -> PopupGeometry:
        margin = 12
        parent_width = max(1, int(parent_width))
        parent_height = max(1, int(parent_height))
        max_inside_width = max(260, parent_width - margin * 2)
        width = min(
            int(max_width),
            max_inside_width,
            max(int(min_width), int(parent_width * 0.42)),
        )
        available_height = max(180, parent_height - margin * 2)
        content_height = int(preferred_height) + max(0, int(item_count) - 3) * 12
        height = min(available_height, max(240, content_height))
        below_y = int(anchor_y) + int(anchor_height) + 8
        above_y = int(anchor_y) - height - 8
        if below_y + height <= parent_height - margin:
            y = below_y
        else:
            y = max(margin, above_y)
        y = max(margin, min(y, parent_height - height - margin))
        if self.is_rtl():
            x = int(anchor_x)
        else:
            x = int(anchor_x) + int(anchor_width) - width
        x = max(margin, min(x, parent_width - width - margin))
        return PopupGeometry(width=width, height=height, x=x, y=y)

    def severity_property(self, item: NotificationViewItem) -> str:
        text = f"{item.level} {item.status}".lower()
        if "expired" in text or "منته" in text:
            return "expired"
        if "today" in text or "اليوم" in text:
            return "today"
        if "critical" in text or "low" in text or "حرج" in text:
            return "critical"
        if "soon" in text or "قريب" in text:
            return "soon"
        return "normal"


class _NotificationItemWidget(QFrame):
    clicked = pyqtSignal()

    def __init__(
        self, item: NotificationViewItem, presenter: NotificationsPresenter, parent=None
    ) -> None:
        super().__init__(parent)
        self._item = item
        self._presenter = presenter
        self.setObjectName("NotificationItem")
        self.setProperty("read", bool(item.read))
        self.setProperty("severity", presenter.severity_property(item))
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setMinimumWidth(0)
        self.setToolTip(_("Read") if item.read else _("Click to mark as read"))
        self.setLayoutDirection(direction_for_rtl(presenter.is_rtl()))
        set_accessibility(
            self,
            name=item.title or _("Notification"),
            description=item.message or item.status,
        )
        self._build()

    def _text_alignment(self) -> Qt.Alignment:
        return leading_alignment(self._presenter.is_rtl())

    def _build(self) -> None:
        root = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(root, 8, 6, 8, 6)
        _layout_rules.set_layout_spacing(root, 4)
        root.addLayout(self._title_row())
        if self._item.product:
            root.addWidget(self._label(self._item.product, "NotificationItemProduct"))
        for line in self._presenter.detail_lines(self._item):
            root.addWidget(self._label(line, "NotificationItemMeta"))

    def _title_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        _layout_rules.set_layout_spacing(row, 8)
        dot = self._label("●", "NotificationUnreadDot")
        dot.setVisible(not self._item.read)
        title = self._label(
            self._item.status or self._item.title or _("Notification"),
            "NotificationItemTitleCompact",
        )
        title.setAlignment(self._text_alignment() | Qt.AlignVCenter)
        timestamp = self._label(self._item.timestamp, "NotificationItemMeta")
        timestamp.setAlignment(
            trailing_alignment(self._presenter.is_rtl()) | Qt.AlignTop
        )
        widgets = (
            [timestamp, title, dot]
            if self._presenter.is_rtl()
            else [dot, title, timestamp]
        )
        for widget in widgets:
            row.addWidget(widget, 1 if widget is title else 0)
        return row

    def _label(self, text: str, object_name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label.setAlignment(self._text_alignment())
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        return label

    def mouseReleaseEvent(self, event):
        try:
            if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
                self.clicked.emit()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Notification item click handling failed", exc_info=True)
        super().mouseReleaseEvent(event)


class NotificationsPanelUiMixin:

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(root, 8, 8, 8, 8)
        _layout_rules.set_layout_spacing(root, 6)
        self.header_row = QHBoxLayout()
        _layout_rules.set_layout_spacing(self.header_row, 6)
        self.title_label = QLabel("")
        self.title_label.setObjectName("NotificationDialogTitle")
        self.title_label.hide()
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("NotificationDialogSummaryCompact")
        self.header_row.setContentsMargins(0, 0, 0, 0)
        self.summary_label.hide()
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("NotificationsList")
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setSpacing(6)
        _layout_rules.set_layout_spacing(self.list_widget, 6)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        _layout_rules.set_list_uniform_item_sizes(self.list_widget, False)
        self.list_widget.setWordWrap(True)
        set_accessibility(
            self.list_widget,
            name=_("Notifications list"),
            description=_("Recent local alerts"),
        )
        self.list_widget.itemClicked.connect(self._on_item_triggered)
        self.list_widget.itemActivated.connect(self._on_item_triggered)
        root.addWidget(self.list_widget, 1)
        self.empty_label = QLabel(_("No notifications yet."))
        self.empty_label.setObjectName("NotificationEmptyLabel")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        set_accessibility(self.empty_label, name=_("No notifications yet."))
        root.addWidget(self.empty_label)
        self.actions_row = QHBoxLayout()
        _layout_rules.set_layout_spacing(self.actions_row, 8)
        self.mark_read_button = self._button(
            _("Read all"), "SecondaryButton", self.mark_all_requested.emit
        )
        self.clear_button = self._button(
            _("Clear"), "SecondaryButton", self.clear_all_requested.emit
        )
        self.close_button = self._button(_("Close"), "PrimaryButton", self.hide_panel)
        root.addLayout(self.actions_row)
        set_tab_order(
            self,
            [
                self.list_widget,
                self.mark_read_button,
                self.clear_button,
                self.close_button,
            ],
        )

    def _button(self, text: str, object_name: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.clicked.connect(slot)
        set_accessibility(button, name=text)
        return button

    def _apply_language_layout(self) -> None:
        self._presenter = NotificationsPresenter(
            getattr(self.parentWidget(), "db_manager", None)
        )
        rtl = self._presenter.is_rtl()
        direction = direction_for_rtl(rtl)
        alignment = leading_alignment(rtl)
        self.setLayoutDirection(direction)
        self.list_widget.setLayoutDirection(direction)
        self.title_label.setAlignment(alignment | Qt.AlignVCenter)
        self.summary_label.setAlignment(trailing_alignment(rtl) | Qt.AlignVCenter)
        clear_layout(self.header_row)
        self.title_label.hide()
        self.summary_label.hide()
        clear_layout(self.actions_row)
        if rtl:
            self.actions_row.addWidget(self.close_button)
            add_stretch(self.actions_row, 1)
            self.actions_row.addWidget(self.clear_button)
            self.actions_row.addWidget(self.mark_read_button)
        else:
            self.actions_row.addWidget(self.mark_read_button)
            self.actions_row.addWidget(self.clear_button)
            add_stretch(self.actions_row, 1)
            self.actions_row.addWidget(self.close_button)
        repolish_widget_tree(self)
