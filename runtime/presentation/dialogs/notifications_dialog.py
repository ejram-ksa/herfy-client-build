from __future__ import annotations
from .notifications_panel import (
    NotificationsPanelUiMixin,
    NotificationsPresenter,
    NotificationViewItem,
    _NotificationItemWidget,
)
import logging
from PyQt5.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractScrollArea,
    QFrame,
    QListWidgetItem,
    QSizePolicy,
    QWidget,
)
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.layout.helpers import resize_widget, set_minimum_height
from runtime.presentation.layout.interface import polish_interface
from runtime.presentation.layout.metrics import UI_METRICS
from runtime.presentation.layout.profiles import apply_profile_properties, profile_for_dimensions
from runtime.presentation.responsive import layout_mode_for_width

logger = logging.getLogger(__name__)


class NotificationsDialog(NotificationsPanelUiMixin, QFrame):
    mark_all_requested = pyqtSignal()
    clear_all_requested = pyqtSignal()
    mark_one_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._presenter = NotificationsPresenter(getattr(parent, "db_manager", None))
        self._max_width = max(440, int(UI_METRICS.notifications_max_width))
        self._min_width = max(380, int(UI_METRICS.notifications_min_width))
        self._preferred_height = max(
            260, int(UI_METRICS.notifications_popup_fallback_height) + 20
        )
        self._items_cache: list[dict] = []
        self._anchor_widget: QWidget | None = None
        self.setObjectName("NotificationsPopup")
        self.setMinimumWidth(self._min_width)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()
        self._build_ui()
        try:
            self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.list_widget.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
            self.list_widget.setResizeMode(self.list_widget.Adjust)
            self.list_widget.setSpacing(6)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "Notifications list no-horizontal-scroll setup failed", exc_info=True
            )
        self._apply_language_layout()
        polish_interface(self, window_width=self.width())

    def show_near(self, anchor: QWidget) -> None:
        parent = self.parentWidget()
        if parent is None or anchor is None:
            return
        self._apply_language_layout()
        parent_rect = parent.rect()
        anchor_top_left = anchor.mapTo(parent, QPoint(0, 0))
        geometry = self._presenter.popup_geometry(
            parent_width=parent_rect.width(),
            parent_height=parent_rect.height(),
            anchor_x=anchor_top_left.x(),
            anchor_y=anchor_top_left.y(),
            anchor_width=anchor.width(),
            anchor_height=anchor.height(),
            min_width=self._min_width,
            max_width=self._max_width,
            preferred_height=self._preferred_height,
            item_count=len(self._items_cache),
        )
        profile = profile_for_dimensions(parent_rect.width(), parent_rect.height())
        apply_profile_properties(self, profile)
        resize_widget(self, QSize(geometry.width, geometry.height))
        target_height = profile.touch_target
        for button in (self.mark_read_button, self.clear_button, self.close_button):
            set_minimum_height(button, target_height)
        self._anchor_widget = anchor
        self.move(geometry.x, geometry.y)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def set_notifications(self, notifications: list[dict]) -> None:
        self._items_cache = list(notifications or [])
        self._apply_language_layout()
        self.list_widget.clear()
        view_items = self._presenter.to_view_items(self._items_cache)
        unread_count = sum((1 for item in view_items if not item.read))
        total_count = len(view_items)
        self.summary_label.setText(self._presenter.summary_text(self._items_cache))
        self.mark_read_button.setEnabled(bool(unread_count))
        self.clear_button.setEnabled(bool(total_count))
        self.empty_label.setVisible(total_count == 0)
        self.list_widget.setVisible(total_count > 0)
        for view_item in view_items:
            self._add_notification_item(view_item)

    def _add_notification_item(self, view_item: NotificationViewItem) -> None:
        widget = _NotificationItemWidget(view_item, self._presenter, self.list_widget)
        widget.clicked.connect(
            lambda idx=view_item.index: self.mark_one_requested.emit(int(idx))
        )
        item = QListWidgetItem(self.list_widget)
        item.setData(Qt.UserRole, int(view_item.index))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        width = max(260, self.list_widget.viewport().width() - 10)
        widget.setMinimumWidth(0)
        hint = widget.sizeHint()
        item.setSizeHint(QSize(width, max(62, hint.height())))
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)

    def hide_panel(self) -> None:
        self._remove_event_filter()
        self.hide()

    def _remove_event_filter(self) -> None:
        try:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Removing notifications event filter failed", exc_info=True)

    def eventFilter(self, obj, event):
        if not self.isVisible():
            return False
        try:
            if event.type() == QEvent.MouseButtonPress:
                if self._click_is_outside_popup(event.globalPos()):
                    self.hide_panel()
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.hide_panel()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Notifications popup event filter failed", exc_info=True)
        return False

    def _click_is_outside_popup(self, global_pos) -> bool:
        widget = QApplication.widgetAt(global_pos)
        anchor = self._anchor_widget
        inside_panel = widget is not None and (
            widget is self or self.isAncestorOf(widget)
        )
        inside_anchor = (
            anchor is not None
            and widget is not None
            and (widget is anchor or anchor.isAncestorOf(widget))
        )
        return widget is None or (not inside_panel and (not inside_anchor))

    def hideEvent(self, event):
        super().hideEvent(event)
        self._remove_event_filter()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            mode = layout_mode_for_width(self.width())
            if getattr(self, "_last_notification_resize_mode", "") == mode:
                return
            self._last_notification_resize_mode = mode
            self._refresh_item_sizes()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Refreshing notification row sizes failed", exc_info=True)

    def _refresh_item_sizes(self) -> None:
        if not hasattr(self, "list_widget"):
            return
        width = max(260, self.list_widget.viewport().width() - 8)
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            widget = self.list_widget.itemWidget(item)
            if item is None or widget is None:
                continue
            widget.setMinimumWidth(0)
            hint = widget.sizeHint()
            item.setSizeHint(QSize(width, max(62, hint.height())))

    def _on_item_triggered(self, item: QListWidgetItem) -> None:
        try:
            if item is not None:
                index = item.data(Qt.UserRole)
                if index is not None:
                    self.mark_one_requested.emit(int(index))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Notification item activation failed", exc_info=True)
