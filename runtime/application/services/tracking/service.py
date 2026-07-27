from __future__ import annotations
from collections.abc import Iterable
from dataclasses import dataclass
from runtime.shared.settings.config import _
from runtime.shared.objects import normalize_int
from runtime.domain.tracking_rows import deduplicate_tracking_records, tracking_record_identity_keys
from runtime.application.services.tracking_runtime import tracking_baseline

@dataclass(frozen=True)
class TrackingBranchFilterState:
    branches: list[str]
    can_view_all: bool
    allow_scope_aggregate: bool
    show_row: bool
    items: list[tuple[str, str]]
    selected_data: str
    disable_selector: bool

@dataclass(frozen=True)
class TrackingBranchUiState:
    active_branch: str
    is_all: bool
    can_create: bool
    branch_text: str
    action_text: str
    add_tooltip: str

def build_branch_filter_state(*, branches: Iterable[str] | None, can_view_all: bool, saved_view: str='') -> TrackingBranchFilterState:
    normalized_branches = [str(branch or '').strip() for branch in branches or [] if str(branch or '').strip()]
    allow_scope_aggregate = len(normalized_branches) > 1
    show_row = bool(normalized_branches) and allow_scope_aggregate
    candidate = str(saved_view or '').strip() or ('all' if allow_scope_aggregate else normalized_branches[0] if normalized_branches else '')
    items: list[tuple[str, str]] = []
    if allow_scope_aggregate:
        label = _('All restaurant branches') if can_view_all else _('My restaurant branches')
        items.append((label, 'all'))
    for branch in normalized_branches:
        items.append((branch, branch))
    allowed_values = {data for _, data in items}
    selected_data = candidate if candidate in allowed_values else items[0][1] if items else ''
    return TrackingBranchFilterState(branches=normalized_branches, can_view_all=bool(can_view_all), allow_scope_aggregate=allow_scope_aggregate, show_row=show_row, items=items, selected_data=selected_data, disable_selector=len(normalized_branches) == 1)

def resolve_view_branch_selection(value: str, *, can_view_all: bool, allow_scope_aggregate: bool) -> str:
    raw_value = str(value or '').strip()
    normalized = raw_value.lower()
    is_all = normalized == 'all' and (bool(can_view_all) or bool(allow_scope_aggregate))
    return 'all' if is_all else raw_value

def build_branch_ui_state(*, active_branch: str, allowed_branches: Iterable[str] | None, can_view_all: bool, can_create: bool) -> TrackingBranchUiState:
    allowed = [str(branch or '').strip() for branch in allowed_branches or [] if str(branch or '').strip()]
    branch_value = str(active_branch or '').strip()
    is_all = bool(branch_value) and branch_value.lower() == 'all'
    if is_all:
        branch_text = _('Viewing all branches') if can_view_all else _('Viewing all allowed branches')
        action_text = _('Select a specific branch to add or update items.')
    elif branch_value:
        branch_text = _('Branch: {branch}').format(branch=branch_value)
        if can_create:
            action_text = _('Add and edit are enabled according to your branch permissions.')
        else:
            action_text = _('View only; no add permission.')
    elif len(allowed) == 1:
        branch_text = _('Branch: {branch}').format(branch=allowed[0])
        if can_create:
            action_text = _('Add and edit are enabled according to your branch permissions.')
        else:
            action_text = _('View only; no add permission.')
    else:
        branch_text = _('Choose a branch')
        action_text = _('Select a branch to view or add shelf-life items.')
    add_tooltip = _('Add or update food shelf-life item') if can_create else _('You do not have permission to add items for the current branch.')
    return TrackingBranchUiState(active_branch=branch_value, is_all=is_all, can_create=bool(can_create), branch_text=branch_text, action_text=action_text, add_tooltip=add_tooltip)
from collections.abc import Callable, Mapping
from typing import Any
NESTED_RECORD_KEYS = ('item', 'product', 'catalog', 'data', 'payload', 'raw')

@dataclass(frozen=True, slots=True)
class CatalogProduct:
    material_number: str
    name: str

    @property
    def display_text(self) -> str:
        if self.material_number and self.name and (self.name != self.material_number):
            return f'{self.material_number} - {self.name}'
        return self.material_number or self.name

    def as_dict(self) -> dict[str, str]:
        return {'material_number': self.material_number, 'name': self.name}

def _sources(row: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    top = dict(row or {})
    rows: list[Mapping[str, Any]] = [top]
    for key in NESTED_RECORD_KEYS:
        nested = top.get(key)
        if isinstance(nested, Mapping):
            rows.append(nested)
    return tuple(rows)

def _first_text(row: Mapping[str, Any] | None, *keys: str) -> str:
    for source in _sources(row):
        for key in keys:
            text = str(source.get(key) or '').strip()
            if text:
                return text
    return ''

def _first_value(row: Mapping[str, Any] | None, *keys: str, default: Any='') -> Any:
    for source in _sources(row):
        for key in keys:
            value = source.get(key)
            if value not in (None, ''):
                return value
    return default

def _looks_like_code(value: Any, material: str='') -> bool:
    text = str(value or '').strip()
    if not text:
        return True
    material_text = str(material or '').strip()
    if material_text and text.casefold() == material_text.casefold():
        return True
    compact = text.replace(' ', '').replace('-', '').replace('_', '')
    return compact.isdigit()

def _better_product_name(candidate: Any, material: str, fallback: Any='') -> str:
    candidate_text = str(candidate or '').strip()
    fallback_text = str(fallback or '').strip()
    if candidate_text and (not _looks_like_code(candidate_text, material)):
        return candidate_text
    if fallback_text and (not _looks_like_code(fallback_text, material)):
        return fallback_text
    return candidate_text or fallback_text or str(material or '').strip()
MATERIAL_FIELD_ALIASES = ('material_number', 'material_code', 'material', 'material_id', 'code', 'materialNumber', 'materialCode', 'materialId', 'matnr', 'item_code', 'itemCode')
PRODUCT_NAME_FIELD_ALIASES = ('name', 'material_name', 'product_name', 'product_description', 'description', 'description_en', 'description_ar', 'material_description', 'display_name', 'food_item_name', 'food_name', 'item_name', 'item_description', 'short_text', 'long_text', 'name_en', 'name_ar', 'materialName', 'productName', 'productDescription', 'descriptionEn', 'descriptionAr', 'materialDescription', 'displayName', 'foodItemName', 'foodName', 'itemName', 'itemDescription', 'shortText', 'longText')

def _row_material(row: Mapping[str, Any] | None) -> str:
    return _first_text(row, *MATERIAL_FIELD_ALIASES)

def _row_name(row: Mapping[str, Any] | None, material: str='') -> str:
    return _better_product_name(_first_text(row, *PRODUCT_NAME_FIELD_ALIASES), material)

def _merge_catalog_rows(primary_rows: Iterable[Mapping[str, Any]] | None, fallback_rows: Iterable[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for row in list(fallback_rows or []) + list(primary_rows or []):
        if not isinstance(row, Mapping):
            continue
        material = _row_material(row)
        if not material:
            continue
        current = merged.get(material.casefold(), {})
        current_name = current.get('name', '')
        name = _better_product_name(_row_name(row, material), material, current_name)
        if not name:
            name = material
        merged[material.casefold()] = {'material_number': material, 'name': name}
    return sorted(merged.values(), key=lambda item: (str(item.get('name', '')).casefold(), str(item.get('material_number', '')).casefold()))

def canonical_tracking_row(row: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(row or {})
    material = _first_text(source, *MATERIAL_FIELD_ALIASES)
    name = _better_product_name(_row_name(source, material), material, material)
    branch = _first_text(source, 'branch', 'branch_code', 'branch_id')
    doc_id = _first_text(source, 'doc_id', 'document_id', 'tracking_id', 'tracked_id', 'item_id', 'uuid', '_id')
    remote_id = _first_text(source, 'id') or doc_id
    if '::' in remote_id:
        id_branch, bare_id = remote_id.split('::', 1)
        branch = branch or id_branch.strip()
        doc_id = doc_id or bare_id.strip()
    else:
        doc_id = doc_id or remote_id
    try:
        quantity = int(_first_value(source, 'quantity', 'qty', 'on_hand', default=0) or 0)
    except (TypeError, ValueError):
        quantity = 0
    projected = dict(source)
    projected.update({'id': f'{branch}::{doc_id}' if branch and doc_id else remote_id or doc_id, 'doc_id': doc_id, 'material_number': material, 'name': name, 'branch': branch, 'quantity': quantity, 'production_date': _first_text(source, 'production_date', 'prod_date', 'productionDate', 'production'), 'expiry_date': _first_text(source, 'expiry_date', 'exp_date', 'expiryDate', 'expiration_date', 'expiration')})
    return projected

def normalize_tracking_catalog(rows: Iterable[Mapping[str, Any]] | None) -> list[CatalogProduct]:
    unique: dict[str, CatalogProduct] = {}
    for row in rows or ():
        projected = canonical_tracking_row(row)
        material = projected['material_number']
        if material:
            unique[material.casefold()] = CatalogProduct(material, projected['name'] or material)
    return sorted(unique.values(), key=lambda product: (product.name.casefold(), product.material_number.casefold()))

def build_tracking_completer_suggestions(rows: Iterable[Mapping[str, Any]] | None) -> list[str]:
    return [product.display_text for product in normalize_tracking_catalog(rows)]

def resolve_tracking_catalog_selection(text: str, rows: Iterable[Mapping[str, Any]] | None) -> CatalogProduct | None:
    requested = str(text or '').strip()
    if ' - ' in requested:
        requested = requested.split(' - ', 1)[0].strip()
    needle = requested.casefold()
    if not needle:
        return None
    products = normalize_tracking_catalog(rows)
    exact = [p for p in products if needle in {p.material_number.casefold(), p.name.casefold()}]
    if exact:
        return exact[0]
    partial = [p for p in products if needle in p.material_number.casefold() or needle in p.name.casefold()]
    return partial[0] if len(partial) == 1 else None

def enrich_tracking_rows_for_display(rows: Iterable[Mapping[str, Any]] | None, catalog_rows: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    catalog = normalize_tracking_catalog(catalog_rows)
    by_material = {p.material_number.casefold(): p.name for p in catalog}
    by_name: dict[str, str] = {}
    duplicated: set[str] = set()
    for product in catalog:
        key = product.name.casefold()
        if key in by_name and by_name[key] != product.material_number:
            duplicated.add(key)
        else:
            by_name[key] = product.material_number
    for key in duplicated:
        by_name.pop(key, None)
    enriched = []
    for row in deduplicate_tracking_records(rows):
        projected = canonical_tracking_row(row)
        material = projected['material_number']
        name = projected['name']
        if not material and name:
            material = by_name.get(name.casefold(), '')
        if material and (not name or _looks_like_code(name, material)):
            name = by_material.get(material.casefold(), material)
        projected['material_number'] = material
        projected['name'] = _better_product_name(name, material, by_material.get(material.casefold(), ''))
        enriched.append(projected)
    return enriched

def row_identity_keys(row: Mapping[str, Any] | None) -> tuple[str, ...]:
    return tracking_record_identity_keys(canonical_tracking_row(row))

def merge_tracking_delta_rows(current_rows: Iterable[Mapping[str, Any]] | None, delta: Mapping[str, Any] | None, *, catalog_rows: Iterable[Mapping[str, Any]] | None, branch_filter: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = enrich_tracking_rows_for_display(current_rows, catalog_rows)
    deletes = {str(x or '').strip() for x in (delta or {}).get('deletes') or () if str(x or '').strip()}
    if deletes:
        rows = [row for row in rows if not deletes.intersection(row_identity_keys(row))]
    index = {key: i for i, row in enumerate(rows) for key in row_identity_keys(row)}
    for incoming in (delta or {}).get('upserts') or ():
        if not isinstance(incoming, Mapping):
            continue
        filtered = branch_filter([dict(incoming)])
        candidate = enrich_tracking_rows_for_display(filtered or [dict(incoming)], catalog_rows)[0]
        position = next((index[k] for k in row_identity_keys(candidate) if k in index), None)
        if not filtered:
            if position is not None:
                rows.pop(position)
        elif position is None:
            rows.append(candidate)
        else:
            rows[position] = candidate
        index = {key: i for i, row in enumerate(rows) for key in row_identity_keys(row)}
    return rows
from datetime import date, datetime
from runtime.shared.strings import clean_text as _text
INVALID_DATE_MESSAGE = _('Invalid date format!')
INVALID_QUANTITY_MESSAGE = _('Quantity must be a positive integer.')
CREATE_REQUIRED_MESSAGE = _('Please select a product and enter quantity.')

@dataclass(frozen=True)
class TrackingCreateInput:
    material_number: str
    quantity: int
    production_date: str
    expiry_date: str

@dataclass(frozen=True)
class TrackingUpdateInput:
    quantity: int
    production_date: str
    expiry_date: str

class TrackingFormService:

    @staticmethod
    def extract_material_number(value: str) -> str:
        text = _text(value)
        return text.split(' - ', 1)[0].strip() if ' - ' in text else text

    @staticmethod
    def _parse_iso_date(value: str) -> date:
        return datetime.strptime(_text(value), '%Y-%m-%d').date()

    def validate_date_order(self, production_date: str, expiry_date: str) -> str:
        try:
            prod = self._parse_iso_date(production_date)
            exp = self._parse_iso_date(expiry_date)
        except (TypeError, ValueError):
            return INVALID_DATE_MESSAGE
        return _('Production date cannot be after expiry date.') if prod > exp else ''

    @staticmethod
    def parse_positive_quantity(value: str) -> tuple[int | None, str]:
        try:
            quantity = int(_text(value))
        except (TypeError, ValueError):
            return (None, INVALID_QUANTITY_MESSAGE)
        return (quantity, '') if quantity > 0 else (None, INVALID_QUANTITY_MESSAGE)

    def _validated_quantity_and_dates(self, *, quantity_text: str, production_date: str, expiry_date: str) -> tuple[int | None, str]:
        quantity, error_message = self.parse_positive_quantity(quantity_text)
        if error_message:
            return (None, error_message)
        error_message = self.validate_date_order(production_date, expiry_date)
        return (None, error_message) if error_message else (quantity, '')

    def prepare_create(self, *, product_text: str, quantity_text: str, production_date: str, expiry_date: str) -> tuple[TrackingCreateInput | None, str]:
        if not _text(product_text) or not _text(quantity_text):
            return (None, CREATE_REQUIRED_MESSAGE)
        material_number = self.extract_material_number(product_text)
        if not material_number:
            return (None, CREATE_REQUIRED_MESSAGE)
        quantity, error_message = self._validated_quantity_and_dates(quantity_text=quantity_text, production_date=production_date, expiry_date=expiry_date)
        if error_message:
            return (None, error_message)
        return (TrackingCreateInput(material_number=material_number, quantity=int(quantity or 0), production_date=_text(production_date), expiry_date=_text(expiry_date)), '')

    def prepare_update(self, *, quantity_text: str, production_date: str, expiry_date: str) -> tuple[TrackingUpdateInput | None, str]:
        quantity, error_message = self._validated_quantity_and_dates(quantity_text=quantity_text, production_date=production_date, expiry_date=expiry_date)
        if error_message:
            return (None, error_message)
        return (TrackingUpdateInput(quantity=int(quantity or 0), production_date=_text(production_date), expiry_date=_text(expiry_date)), '')
from runtime.shared.strings import clean_text

def lower_text(value: Any='') -> str:
    return str(clean_text(value)).lower()

def _lower(value: Any='') -> str:
    """Internal compatibility alias retained after module consolidation."""
    return lower_text(value)
import logging
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
ACTION_CREATE = 'create'
ACTION_UPDATE = 'update'
ACTION_DELETE = 'delete'
logger = logging.getLogger(__name__)

class TrackingBranchAccessService:

    def __init__(self, db_manager: Any, *, api_client_provider: Callable[[], Any], user_id_provider: Callable[[], str]):
        self.db_manager = db_manager
        self._api_client_provider = api_client_provider
        self._user_id_provider = user_id_provider

    def resolve_write_branch(self) -> tuple[str, str]:
        if not self._api_client_provider():
            return ('', '')
        try:
            return (_text(self.db_manager._pick_branch_for_write()), '')
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            return ('', _text(exc) or 'Please select a branch to add/update.')

    def validate_action(self, branch: str, *, action: str) -> str:
        if not self._api_client_provider():
            return ''
        branch = _text(branch)
        action = _lower(action)
        if action == ACTION_CREATE and branch and (not self.db_manager.can_create_tracking(branch)):
            return "You don't have permission to add items in this branch."
        if action == ACTION_UPDATE and (not self.db_manager.can_update_tracking(branch)):
            return "You don't have permission to edit items in this branch."
        if action == ACTION_DELETE and (not self.db_manager.can_delete_tracking(branch)):
            return "You don't have permission to delete items in this branch."
        return ''

    def allowed_branches(self) -> list[str]:
        return [branch for branch in (_text(item) for item in self.db_manager.allowed_branches() or []) if branch]

    def can_view_all_branches(self) -> bool:
        return bool(self.db_manager.can_view_all_branches())

    def current_branch_context(self) -> str:
        return _text(self.db_manager.get_active_branch()) or 'all'

    def _saved_view_branch(self) -> str:
        uid = self._user_id_provider()
        return _text(self.db_manager.get_setting(f'last_view_branch_{uid}', '')) if uid else ''

    @staticmethod
    def _filter_state_to_dict(state) -> dict[str, Any]:
        return {'branches': state.branches, 'can_view_all': state.can_view_all, 'allow_scope_aggregate': state.allow_scope_aggregate, 'show_row': state.show_row, 'items': state.items, 'selected_data': state.selected_data, 'disable_selector': state.disable_selector}

    @staticmethod
    def _ui_state_to_dict(state) -> dict[str, Any]:
        return {'active_branch': state.active_branch, 'is_all': state.is_all, 'can_create': state.can_create, 'branch_text': state.branch_text, 'action_text': state.action_text, 'add_tooltip': state.add_tooltip}

    def get_filter_state(self) -> dict[str, Any]:
        state = build_branch_filter_state(branches=self.allowed_branches(), can_view_all=self.can_view_all_branches(), saved_view=self._saved_view_branch())
        return self._filter_state_to_dict(state)

    def apply_view_selection(self, value: str) -> str:
        raw_value = _text(value)
        uid = self._user_id_provider()
        try:
            if uid:
                self.db_manager.set_setting(f'last_view_branch_{uid}', raw_value)
                if _lower(raw_value) != 'all':
                    self.db_manager.set_setting(f'last_branch_{uid}', raw_value)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('Tracking branch selection persistence failed', exc_info=True)
        active_branch = resolve_view_branch_selection(raw_value, can_view_all=self.can_view_all_branches(), allow_scope_aggregate=len(self.allowed_branches()) > 1)
        self.db_manager.set_active_branch(active_branch)
        return active_branch

    def get_ui_state(self) -> dict[str, Any]:
        active_branch = _text(self.db_manager.get_active_branch())
        is_all = bool(active_branch) and active_branch.lower() == 'all'
        can_create = bool(active_branch) and (not is_all) and self.db_manager.can_create_tracking(active_branch)
        state = build_branch_ui_state(active_branch=active_branch, allowed_branches=self.allowed_branches(), can_view_all=self.can_view_all_branches(), can_create=can_create)
        return self._ui_state_to_dict(state)

    def filter_rows(self, rows: list | None) -> list:
        view = _lower(self.db_manager.get_active_branch())
        if view and view != 'all':
            return deduplicate_tracking_records((row for row in rows or [] if _lower(row.get('branch')) == view))
        return deduplicate_tracking_records(rows)

    def snapshot_rows(self) -> list:
        snapshot = tracking_baseline.snapshot()
        if snapshot.ready:
            return self.filter_rows(list(snapshot.rows))
        return []

    def items_truncated(self) -> bool:
        return bool(getattr(self._api_client_provider(), '_items_truncated', False))

class TrackingCatalogService:

    def __init__(self, db_manager: Any, *, api_client_provider: Callable[[], Any]):
        self.db_manager = db_manager
        self._api_client_provider = api_client_provider

    def _usage_catalog_rows(self, *, force_network: bool=False) -> list[dict]:
        if force_network and hasattr(self.db_manager, 'refresh_usage_products_from_server'):
            try:
                rows = self.db_manager.refresh_usage_products_from_server(force_refresh=True)
                if rows:
                    return list(rows or [])
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug('Unable to refresh usage catalog for tracking names', exc_info=True)
        local_rows: list[dict] = []
        if hasattr(self.db_manager, 'fetch_usage_products'):
            try:
                local_rows = list(self.db_manager.fetch_usage_products() or [])
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug('Unable to read local usage catalog for tracking names', exc_info=True)
        if local_rows or force_network:
            return local_rows
        if hasattr(self.db_manager, 'refresh_usage_products_from_server'):
            try:
                return list(self.db_manager.refresh_usage_products_from_server(force_refresh=False) or [])
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug('Unable to seed usage catalog for tracking names', exc_info=True)
        return []

    def catalog_products(self, *, force_network: bool=False) -> list[dict[str, str]]:
        local_rows = list(self.db_manager.fetch_stored_products() or [])
        usage_rows = self._usage_catalog_rows(force_network=force_network)
        local_catalog = _merge_catalog_rows(local_rows, usage_rows)
        client = self._api_client_provider()
        if client is None or (local_catalog and (not force_network)):
            return local_catalog
        try:
            remote_rows = list(client.list_stored_products() or [])
            if remote_rows and hasattr(self.db_manager, 'merge_remote_stored_products'):
                self.db_manager.merge_remote_stored_products(remote_rows)
                refreshed_rows = list(self.db_manager.fetch_stored_products() or [])
                return _merge_catalog_rows(refreshed_rows, usage_rows)
            return _merge_catalog_rows(remote_rows, usage_rows) or local_catalog
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.warning('Unable to refresh tracking catalog from server', exc_info=True)
            return local_catalog

    def resolve_product(self, product_text: str, *, force_network: bool=False) -> dict[str, str] | None:
        product = resolve_tracking_catalog_selection(product_text, self.catalog_products(force_network=force_network))
        return product.as_dict() if product is not None else None

    def stored_product_exists(self, material_number: str) -> bool:
        return self.resolve_product(material_number, force_network=bool(self._api_client_provider())) is not None
from runtime.domain.remote_ids import qualify_remote_doc_id, split_cloud_id, valid_remote_doc_id
ACTION_CREATE = 'create'
ACTION_UPDATE = 'update'
ACTION_DELETE = 'delete'
NOT_FOUND_MESSAGE = 'Food item was not found.'
MISSING_SERVER_ID_MESSAGE = 'Server record id is missing. Refresh shelf-life data and try again.'
CATALOG_MESSAGE = 'This food item was not found in the product catalog.'

@dataclass(frozen=True)
class TrackingRecordSelection:
    record: dict[str, Any] | None
    message: str = ''
    requires_refresh: bool = False

class TrackingService:

    def __init__(self, db_manager: Any):
        self.db_manager = db_manager
        self.branch_access = TrackingBranchAccessService(db_manager, api_client_provider=self._api_client, user_id_provider=self._current_user_id)
        self.catalog = TrackingCatalogService(db_manager, api_client_provider=self._api_client)

    def _app_state(self):
        return getattr(self.db_manager, 'app_state', None)

    def _api_client(self):
        return getattr(self._app_state(), 'api_client', None)

    def _current_user_id(self) -> str:
        try:
            user = getattr(self._app_state(), 'current_user', None)
            return _text(getattr(user, 'uid', ''))
        except SERVICE_OPERATION_EXCEPTIONS:
            return ''

    @staticmethod
    def _failure(message: str) -> tuple[bool, str, str]:
        return (False, '', _text(message))

    def _db_result(self, ok: bool, fallback_success: str='') -> tuple[bool, str, str]:
        return (bool(ok), self.db_manager.last_message or _text(fallback_success), self.db_manager.last_error)

    def _resolve_write_branch(self) -> tuple[str, str]:
        return self.branch_access.resolve_write_branch()

    def _validate_branch_action(self, branch: str, *, action: str) -> str:
        return self.branch_access.validate_action(branch, action=action)

    def _resolve_record_id(self, row: dict) -> str:
        if not isinstance(row, dict):
            return ''
        if self._api_client():
            _remote_branch, doc_id = split_cloud_id(_text(row.get('doc_id') or row.get('id')))
            if not valid_remote_doc_id(doc_id):
                return ''
            return qualify_remote_doc_id(_text(row.get('branch')), doc_id)
        return _text(row.get('id'))

    def _prepare_record_action(self, record: dict | None, *, action: str) -> tuple[dict, str]:
        row = record if isinstance(record, dict) else {}
        if not row:
            return ({}, NOT_FOUND_MESSAGE)
        if self._api_client() and (not self._resolve_record_id(row)):
            return ({}, MISSING_SERVER_ID_MESSAGE)
        permission_error = self._validate_branch_action(_text(row.get('branch')), action=action)
        return ({}, permission_error) if permission_error else (row, '')

    @staticmethod
    def _find_row_by_product_id(rows: list | None, product_id: Any) -> dict | None:
        needle = _text(product_id)
        return next((row for row in rows or [] if _text((row or {}).get('id')) == needle), None)

    def select_record_for_action(self, *, product_id: Any, rows: list | None, action: str) -> TrackingRecordSelection:
        row = self._find_row_by_product_id(rows, product_id)
        if not row:
            return TrackingRecordSelection(record=None, message=NOT_FOUND_MESSAGE)
        prepared, error_message = self._prepare_record_action(row, action=action)
        if error_message:
            return TrackingRecordSelection(record=None, message=error_message, requires_refresh=error_message == MISSING_SERVER_ID_MESSAGE)
        return TrackingRecordSelection(record=prepared)

    def _modify_item(self, action: str, row: dict, *, quantity: int | None=None, production_date: str='', expiry_date: str='') -> tuple[bool, str, str]:
        record_id = self._resolve_record_id(row)
        if _lower(action) == ACTION_UPDATE:
            ok = self.db_manager.modify_tracked_product(action, record_id, int(quantity or 0), production_date, expiry_date, silent=True)
        else:
            ok = self.db_manager.modify_tracked_product(action, record_id, silent=True)
        return self._db_result(bool(ok))

    @staticmethod
    def _tracking_payload(*, branch: str='', material_number: str='', expiry_date: str='') -> dict[str, str]:
        return {'branch': _text(branch), 'material_number': _text(material_number), 'expiry_date': _text(expiry_date)}

    @classmethod
    def _tracking_payload_from_row(cls, row: dict | None) -> dict[str, str]:
        row = row if isinstance(row, dict) else {}
        return cls._tracking_payload(branch=row.get('branch', ''), material_number=row.get('material_number', ''), expiry_date=row.get('expiry_date', ''))

    def _emit_tracking_updated(self, action: str, payload: dict | None=None) -> None:
        state = self._app_state()
        if state is None:
            return
        action_name = _lower(action)
        data = dict(payload or {})
        data.setdefault('action', action_name)
        if action_name == ACTION_DELETE:
            state.emit_item_deleted('tracking', data)
        else:
            state.emit_item_updated('tracking', data)

    def _emit_row_change(self, action: str, row: dict | None) -> None:
        self._emit_tracking_updated(action, self._tracking_payload_from_row(row))

    def _find_existing_row(self, rows: list | None, *, material_number: str, expiry_date: str, branch: str) -> dict | None:
        material_number = _text(material_number)
        expiry_date = _text(expiry_date)
        branch = _text(branch)
        for row in rows or []:
            if _text(row.get('material_number')) != material_number:
                continue
            if _text(row.get('expiry_date')) != expiry_date:
                continue
            if self._api_client() and _text(row.get('branch')) != branch:
                continue
            return row
        return None

    def fetch_rows(self, *, cloud: bool, force_network: bool=False) -> list:
        if cloud and self._api_client():
            if not force_network and hasattr(self.db_manager, 'fetch_cached_tracked_products'):
                rows = self.db_manager.fetch_cached_tracked_products()
            else:
                rows = self.db_manager.fetch_tracked_products()
        else:
            rows = self.db_manager.fetch_tracked_products_local_newconn()
        snapshot = tracking_baseline.publish(rows, source='network' if force_network else 'cache')
        return list(snapshot.rows)

    def catalog_products(self, *, force_network: bool=False) -> list[dict[str, str]]:
        return self.catalog.catalog_products(force_network=force_network)

    def resolve_catalog_product(self, product_text: str, *, force_network: bool=False) -> dict[str, str] | None:
        return self.catalog.resolve_product(product_text, force_network=force_network)

    def enrich_rows_for_display(self, rows: list | None, catalog_rows: list | None) -> list[dict[str, Any]]:
        return enrich_tracking_rows_for_display(rows, catalog_rows)

    def merge_visible_delta_rows(self, current_rows: list[dict] | None, delta: dict | None, *, catalog_rows: list[dict] | None) -> list[dict[str, Any]]:
        return merge_tracking_delta_rows(current_rows, delta, catalog_rows=catalog_rows, branch_filter=self.filter_rows_for_active_branch)

    def stored_product_exists(self, material_number: str) -> bool:
        return self.catalog.stored_product_exists(material_number)

    def create_or_merge_item(self, *, material_number: str, quantity: int, production_date: str, expiry_date: str, current_rows: list | None=None) -> tuple[bool, str, str]:
        product = self.resolve_catalog_product(material_number, force_network=bool(self._api_client()))
        if product is None:
            return self._failure(_(CATALOG_MESSAGE))
        material_number = _text(product.get('material_number'))
        material_name = _text(product.get('name') or material_number)
        quantity = normalize_int(quantity, 0)
        write_branch, branch_error = self._resolve_write_branch()
        if branch_error:
            return self._failure(branch_error)
        permission_error = self._validate_branch_action(write_branch, action=ACTION_CREATE)
        if permission_error:
            return self._failure(permission_error)
        existing = self._find_existing_row(current_rows, material_number=material_number, expiry_date=expiry_date, branch=write_branch)
        try:
            if existing:
                result = self._modify_item(ACTION_UPDATE, existing, quantity=normalize_int(existing.get('quantity'), 0) + quantity, production_date=production_date, expiry_date=expiry_date)
                if result[0]:
                    self._emit_tracking_updated(ACTION_UPDATE, self._tracking_payload(branch=write_branch, material_number=material_number, expiry_date=expiry_date))
                return result
            self.db_manager.add_tracked_product(material_number, quantity, production_date, expiry_date, material_name)
            self._emit_tracking_updated(ACTION_CREATE, self._tracking_payload(branch=write_branch, material_number=material_number, expiry_date=expiry_date))
            return self._db_result(True, 'Food item added.')
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            return self._failure(str(exc))

    def update_item(self, record: dict | None, *, quantity: int, production_date: str, expiry_date: str) -> tuple[bool, str, str]:
        row, error_message = self._prepare_record_action(record, action=ACTION_UPDATE)
        if error_message:
            return self._failure(error_message)
        result = self._modify_item(ACTION_UPDATE, row, quantity=quantity, production_date=production_date, expiry_date=expiry_date)
        if result[0]:
            self._emit_row_change(ACTION_UPDATE, row)
        return result

    def delete_item(self, record: dict | None) -> tuple[bool, str, str]:
        row, error_message = self._prepare_record_action(record, action=ACTION_DELETE)
        if error_message:
            return self._failure(error_message)
        result = self._modify_item(ACTION_DELETE, row)
        if result[0]:
            self._emit_row_change(ACTION_DELETE, row)
        return result

    def allowed_branches(self) -> list[str]:
        return self.branch_access.allowed_branches()

    def can_view_all_branches(self) -> bool:
        return self.branch_access.can_view_all_branches()

    def is_cloud_mode(self) -> bool:
        return bool(self._api_client())

    def current_branch_context(self) -> str:
        return self.branch_access.current_branch_context()

    def get_branch_filter_state(self) -> dict[str, Any]:
        return self.branch_access.get_filter_state()

    def apply_view_branch_selection(self, value: str) -> str:
        return self.branch_access.apply_view_selection(value)

    def get_branch_ui_state(self) -> dict[str, Any]:
        return self.branch_access.get_ui_state()

    def filter_rows_for_active_branch(self, rows: list | None) -> list:
        return self.branch_access.filter_rows(rows)

    def snapshot_rows(self) -> list:
        return self.branch_access.snapshot_rows()

    def items_truncated(self) -> bool:
        return self.branch_access.items_truncated()
