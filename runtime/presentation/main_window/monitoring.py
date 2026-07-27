from __future__ import annotations
import logging
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from datetime import date, datetime, timedelta
from runtime.shared.booleans import parse_bool
from runtime.shared.objects import normalize_int
from runtime.application.services.monitoring_engine import MonitoringEngine
from runtime.application.services.tracking_store import tracking_store
from runtime.application.services.expiry_status import ExpiryThresholds, classify_days
logger = logging.getLogger(__name__)

class MainWindowMonitoringMixin:
    _expiry_token = 0

    def _compute_monitor_interval_minutes(self) -> int:
        try:
            active_mins = min(1440, max(5, int(self.db_manager.get_setting('monitoring_active_check_interval_minutes', '15'))))
        except UI_OPERATION_EXCEPTIONS:
            active_mins = 30
        try:
            background_mins = min(1440, max(active_mins, int(self.db_manager.get_setting('monitoring_background_check_interval_minutes', str(max(active_mins, 30))))))
        except UI_OPERATION_EXCEPTIONS:
            background_mins = max(active_mins, 30)
        hidden = self.isHidden() or not self.isVisible()
        return background_mins if hidden else active_mins

    def _apply_monitor_schedule(self, *, restart: bool=True):
        try:
            mins = self._compute_monitor_interval_minutes()
            self.check_interval_timer.setInterval(max(5, mins) * 60 * 1000)
            if restart:
                self.check_interval_timer.start()
        except UI_OPERATION_EXCEPTIONS:
            logger.exception('Failed to apply monitor schedule')

    def set_daily_timer(self):
        """Set daily timer."""
        now_ = datetime.now()
        tomorrow_ = date.today() + timedelta(days=1)
        mid_ = datetime.combine(tomorrow_, datetime.min.time())
        ms_ = int((mid_ - now_).total_seconds() * 1000)
        self.daily_timer.setSingleShot(True)
        self.daily_timer.start(ms_)

    def update_daily(self):
        """Update daily."""
        self.check_expiry()
        self._sync_notifications_panel_direction()
        self.set_daily_timer()

    def load_tracked_products(self, preloaded: list | None=None, show_busy: bool=True):
        """Monitoring hook that never reloads the tracking interface."""
        del preloaded, show_busy
        self.check_expiry()

    @staticmethod
    def _notification_location_fields(row: dict, branch: str='') -> dict[str, str]:
        data = row if isinstance(row, dict) else {}
        branch_value = str(branch or data.get('branch') or data.get('branch_id') or data.get('branchCode') or data.get('branch_code') or '').strip()
        store_name = str(data.get('store') or data.get('store_name') or data.get('location') or data.get('branch_name') or data.get('name_en') or data.get('name') or '').strip()
        branch_name = str(data.get('branch_name') or data.get('branch_display') or data.get('branch_label') or '').strip()
        return {'store': store_name, 'store_name': store_name, 'branch_name': branch_name, 'branch_label': str(data.get('branch_label') or branch_name or branch_value).strip(), 'region': str(data.get('region') or data.get('region_name') or '').strip(), 'area': str(data.get('area') or data.get('area_name') or '').strip()}

    def _process_server_alerts(self, alerts: list, thresholds: ExpiryThresholds):
        events = []
        for alert in alerts or []:
            branch = str(alert.get('branch_id') or '').strip()
            mat = str(alert.get('material_number') or '').strip()
            message = str(alert.get('message') or mat or '').strip()
            product_name = message.split(' quantity is ', 1)[0].split(' expires', 1)[0].strip() or mat
            qty = normalize_int(alert.get('current_qty'), 0)
            days_remaining = alert.get('days_remaining')
            try:
                rd_ = int(days_remaining) if days_remaining is not None else 0
            except (TypeError, ValueError):
                rd_ = 0
            severity = str(alert.get('severity') or 'warning').strip().lower()
            alert_type = str(alert.get('alert_type') or '').strip()
            if alert_type == 'quantity_low':
                st_text = _('Low Quantity')
                severity_rank = 3
            else:
                status = classify_days(rd_, thresholds)
                st_text = status.display_text
                severity = status.severity
                severity_rank = status.severity_rank
            events.append(self.notifications_service.build_event(product_name=product_name, qty=qty, st_text=st_text, rd_=rd_, branch=branch, material_number=mat, expiry_date=str(alert.get('expiry_date') or ''), severity=severity or alert_type or st_text, source='server', severity_rank=severity_rank, **self._notification_location_fields(alert, branch)))
        return events

    def check_expiry(self, preloaded: list | None=None, *, allow_network: bool=False):
        del allow_network
        try:
            if not parse_bool(self.db_manager.get_setting('enable_alerts', 'True'), True):
                return
            if getattr(self, '_expiry_running', False):
                return
            self._expiry_running = True
            self._expiry_token += 1
            token = self._expiry_token
            thresholds = ExpiryThresholds.from_settings(self.db_manager)

            def _fetch_all(progress_callback=None):
                del progress_callback
                return {'alerts': [], 'snapshot': tracking_store.snapshot()}
            self._start_logged_worker(_fetch_all, on_result=lambda res: self._on_expiry_result(token, res, thresholds), on_finished=lambda: self._on_expiry_finished(token), error_handler=lambda msg: logging.error('check_expiry worker: %s', msg), operation_key='expiry_check')
        except UI_OPERATION_EXCEPTIONS as e:
            logging.error('check_expiry start error: %s', e)
            self._expiry_running = False

    def _on_expiry_result(self, token: int, payload, thresholds: ExpiryThresholds):
        if token != getattr(self, '_expiry_token', 0):
            return
        payload = payload or {}
        alerts = payload.get('alerts') if isinstance(payload, dict) else []
        snapshot = payload.get('snapshot') if isinstance(payload, dict) else None
        records = tuple(getattr(snapshot, 'records', ()) or ())
        server_events = self._process_server_alerts(alerts, thresholds) if alerts else []
        local_events = []
        engine = getattr(self, '_monitoring_engine', None)
        if engine is None:
            engine = MonitoringEngine()
            self._monitoring_engine = engine
        transitions = engine.evaluate(records=records, now=datetime.now(), policy=thresholds)
        for transition in transitions:
            alert = transition.alert
            if alert is None:
                continue
            record = alert.record
            key = alert.key
            local_events.append(self.notifications_service.build_event(product_name=record.product_name, qty=record.quantity, st_text=alert.display_text, rd_=int(alert.days_left), branch=key.branch_code, material_number=key.material_number, production_date=key.production_date.isoformat() if key.production_date else '', expiry_date=key.expiry_date.isoformat(), severity=str(alert.state.value), source='local', severity_rank=alert.severity, branch_name=record.branch_name))
        combined: dict[str, dict] = {}
        for event in [*server_events, *local_events]:
            key = self.notifications_service.engine.alert_key(event)
            current = combined.get(key)
            if current is None or normalize_int(event.get('severity_rank'), 0) > normalize_int(current.get('severity_rank'), 0):
                combined[key] = event
        self.notifications_service.publish_alerts(list(combined.values()))

    def _on_expiry_finished(self, token: int):
        if token != getattr(self, '_expiry_token', 0):
            return
        self._expiry_running = False
