from __future__ import annotations
from runtime.shared.settings.config import _
from runtime.shared.objects import normalize_int

class NotificationMessageFormatter:
    """Build user-facing notification text outside Qt widget classes."""

    @staticmethod
    def clean_product_name(value: str) -> str:
        text = str(value or '').strip()
        if text.startswith('[') and ']' in text:
            text = text.split(']', 1)[1].strip()
        return text

    @staticmethod
    def store_label(branch: str) -> str:
        value = str(branch or '').strip()
        if not value:
            return ''
        compact = value.replace(' ', '')
        if compact.upper().startswith('H'):
            return value
        if compact.isdigit():
            return f'H{compact}'
        return value

    @staticmethod
    def explicit_store(payload: dict) -> str:
        for key in ('store', 'store_name', 'location', 'store_display'):
            value = str(payload.get(key) or '').strip()
            if value:
                return value
        return ''

    @staticmethod
    def branch_label(payload: dict) -> str:
        value = str(payload.get('branch') or payload.get('branch_id') or payload.get('branch_code') or payload.get('branch_label') or '').strip()
        if not value:
            return ''
        compact = value.replace(' ', '')
        if compact.upper().startswith('H') and compact[1:].isdigit():
            value = compact[1:]
            compact = value
        if compact.isdigit():
            value = f'#{compact}'
        region = str(payload.get('region') or payload.get('region_name') or payload.get('area') or payload.get('area_name') or '').strip()
        return f'{value} ({region})' if value and region else value

    @staticmethod
    def int_or_none(value) -> int | None:
        try:
            if value in (None, ''):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def days_line(self, payload: dict) -> tuple[str, str]:
        days_expired = self.int_or_none(payload.get('days_expired'))
        days_remaining = self.int_or_none(payload.get('days_remaining'))
        kind = str(payload.get('status_kind') or payload.get('kind') or '').lower()
        days_text = str(payload.get('days_text') or '').strip()
        is_overdue = bool(days_expired and days_expired > 0) or kind == 'expired'
        if days_remaining is not None and days_remaining < 0:
            is_overdue = True
            days_expired = abs(days_remaining)
        if is_overdue:
            count = days_expired if days_expired is not None else None
            value = f"{count} {(_('Day') if count == 1 else _('Days'))}" if count is not None else days_text
            return (_('Overdue'), value.strip())
        if days_remaining is not None:
            value = f"{days_remaining} {(_('Day') if days_remaining == 1 else _('Days'))}"
            return (_('Remaining'), value.strip())
        return (_('Remaining'), days_text) if days_text else ('', '')

    @staticmethod
    def status_display(payload: dict) -> str:
        kind = str(payload.get('status_kind') or payload.get('kind') or '').strip().lower()
        mapping = {'expired': _('Expired'), 'expires_today': _('Expires today'), 'expires_tomorrow': _('Expires tomorrow'), 'expiring_high': _('Critical'), 'expiring_soon': _('Expiring Soon'), 'valid': _('Valid')}
        if kind in mapping:
            return str(mapping[kind])
        raw = str(payload.get('status_label') or payload.get('status') or '').strip()
        low = raw.lower()
        if 'expired' in low or 'overdue' in low:
            return _('Expired')
        if 'today' in low:
            return _('Expires today')
        if 'tomorrow' in low:
            return _('Expires tomorrow')
        if 'critical' in low or 'high' in low:
            return _('Critical')
        if 'soon' in low or 'expiring' in low:
            return _('Expiring Soon')
        return raw

    def format_message(self, payload: dict) -> str:
        product = self.clean_product_name(str(payload.get('product') or payload.get('product_name') or payload.get('item_name') or ''))
        status = self.status_display(payload)
        store = self.explicit_store(payload)
        branch = self.branch_label(payload)
        material = str(payload.get('material_number') or '').strip()
        fallback = str(payload.get('message') or '').strip()
        lines: list[str] = []
        if store:
            lines.append(f'Store: {store}')
        if branch:
            lines.append(f'Branch: {branch}')
        if material:
            lines.append(f"{_('Material number')}: {material}")
        if product:
            lines.append(f'Item Name: {product}')
        if status:
            lines.append(f"{_('Status')}: {status}")
        days_label, days_value = self.days_line(payload)
        if days_label and days_value:
            lines.append(f'{days_label}: {days_value}')
        body = '\n'.join(lines).strip()
        return body or fallback

    @staticmethod
    def severity_rank(payload: dict) -> int:
        return normalize_int(payload.get('severity_rank'), 0)

    def format_summary_message(self, payloads: list[dict]) -> str:
        total = len(payloads)
        stores = sorted({self.explicit_store(item) for item in payloads if self.explicit_store(item)})
        branches = sorted({self.branch_label(item) for item in payloads if self.branch_label(item)})
        expired = sum((1 for item in payloads if self.status_display(item) == _('Expired')))
        today = sum((1 for item in payloads if self.status_display(item) == _('Expires today')))
        critical = sum((1 for item in payloads if self.status_display(item) == _('Critical')))
        lines = [f"{_('Items')}: {total}"]
        if stores:
            shown = ', '.join(stores[:4])
            if len(stores) > 4:
                shown = f'{shown} +{len(stores) - 4}'
            lines.append(f'Stores: {shown}')
        if branches:
            shown = ', '.join(branches[:4])
            if len(branches) > 4:
                shown = f'{shown} +{len(branches) - 4}'
            lines.append(f'Branches: {shown}')
        status_parts: list[str] = []
        if expired:
            status_parts.append(f"{_('Expired')}: {expired}")
        if today:
            status_parts.append(f"{_('Expires today')}: {today}")
        if critical:
            status_parts.append(f"{_('Critical')}: {critical}")
        if status_parts:
            lines.append(' | '.join(status_parts))
        lead_names = []
        for item in payloads[:3]:
            name = self.clean_product_name(str(item.get('product') or item.get('product_name') or ''))
            material = str(item.get('material_number') or '').strip()
            if name and material:
                lead_names.append(f'{material} - {name}')
            elif name:
                lead_names.append(name)
            elif material:
                lead_names.append(material)
        if lead_names:
            lines.append('\n'.join(lead_names))
        return '\n'.join((line for line in lines if line)).strip()
import re
from dataclasses import dataclass
from html import escape
from typing import Any
_BRANCH_CODE_RE = re.compile('[Hh]?(\\d+)')

@dataclass(frozen=True)
class NotificationToastViewModel:
    """Pure presentation model for the branded expiry reminder toast."""
    title: str
    detail_html: str
    summary_text: str
    has_details: bool
    duration_s: int

def build_expiry_toast_view_model(*, title: str, payload: dict | None, duration_s: int, formatter: NotificationMessageFormatter | None=None) -> NotificationToastViewModel:
    """Normalize notification payload into safe text before it reaches Qt widgets."""
    data = dict(payload or {})
    active_formatter = formatter or NotificationMessageFormatter()
    title_text = _clean_text(title) or _clean_text(data.get('title')) or _('Products expiration tracking')
    duration = max(3, min(60, normalize_int(duration_s or data.get('duration_s'), 6)))
    summary = _clean_text(data.get('message'))
    if _is_summary(data) or not _has_detail_fields(data):
        return NotificationToastViewModel(title=title_text, detail_html='', summary_text=summary, has_details=False, duration_s=duration)
    return NotificationToastViewModel(title=title_text, detail_html=_detail_html(data, active_formatter), summary_text='', has_details=True, duration_s=duration)

def format_branch_code(value: Any) -> str:
    raw = _clean_text(value)
    if not raw:
        return ''
    compact = raw.replace(' ', '')
    match = _BRANCH_CODE_RE.fullmatch(compact)
    if match:
        return f'#{match.group(1)}'
    return raw

def _is_summary(data: dict) -> bool:
    value = data.get('is_summary')
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'summary'}

def _has_detail_fields(data: dict) -> bool:
    return any((_clean_text(data.get(key)) for key in ('product', 'product_name', 'item_name', 'itemName', 'display_product', 'branch', 'branch_id', 'branch_code', 'branch_label', 'store', 'store_name', 'expiry_date', 'days_remaining', 'days_expired', 'days_text')))

def _detail_html(data: dict, formatter: NotificationMessageFormatter) -> str:
    item = _product_name(data, formatter)
    store = _store_name(data)
    branch = _branch_line(data)
    expiry = _clean_text(data.get('expiry_date')) or '-'
    days_label, days_value = formatter.days_line(data)
    if not days_value:
        days_value = _clean_text(data.get('days_text')) or '-'
    if _is_overdue(data, days_label):
        days_label = 'Days Overdue'
    else:
        days_label = 'Days Remaining'
    lines = (('Item Name', item or '-', False), ('Store', store or '-', False), ('Branch', branch or '-', False), ('Expiry Date', expiry, False), (days_label, days_value, True))
    return ''.join((_detail_line(label, value, danger) for label, value, danger in lines))

def _detail_line(label: str, value: Any, danger: bool) -> str:
    value_style = 'color:#D91515;font-weight:900;' if danger else 'color:#4B5563;'
    return f"<div style='margin:3px 0;'><span style='color:#081A3A;font-weight:900;'>{escape(str(label))}: </span><span style='{value_style}'>{escape(str(value))}</span></div>"

def _product_name(data: dict, formatter: NotificationMessageFormatter) -> str:
    raw = _first_text(data, ('product', 'product_name', 'item_name', 'itemName', 'display_product'))
    return formatter.clean_product_name(raw)

def _store_name(data: dict) -> str:
    return _first_text(data, ('store', 'store_name', 'location', 'store_display'))

def _branch_line(data: dict) -> str:
    branch = _first_text(data, ('branch', 'branch_id', 'branch_code', 'branch_label', 'branch_name'))
    branch = format_branch_code(branch)
    region = _first_text(data, ('region', 'region_name', 'area', 'area_name'))
    if branch and region:
        return f'{branch} ({region})'
    return branch

def _is_overdue(data: dict, days_label: str) -> bool:
    kind = _clean_text(data.get('status_kind') or data.get('kind')).lower()
    label = _clean_text(days_label).lower()
    if kind == 'expired' or label == 'overdue':
        return True
    return normalize_int(data.get('days_remaining'), 0) < 0

def _first_text(data: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _clean_text(data.get(key))
        if value:
            return value
    return ''

def _clean_text(value: Any) -> str:
    return str(value or '').strip()
__all__ = ['NotificationMessageFormatter', 'NotificationToastViewModel', 'build_expiry_toast_view_model', 'format_branch_code']
