from __future__ import annotations
import logging
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.infrastructure.persistence import is_transient_remote_error
logger = logging.getLogger(__name__)

class UsageLocalRepositoryMixin:

    def _emit_usage_event(self, action: str, payload=None):
        state = getattr(self, 'app_state', None)
        if state is None:
            return
        data = dict(payload or {})
        data.setdefault('action', str(action or '').strip().lower())
        if str(action or '').strip().lower() == 'delete':
            state.emit_item_deleted('usage', data)
        else:
            state.emit_item_updated('usage', data)

    def fetch_usage_products(self):
        with self._db_lock:
            conn = self._fresh_connection()
            try:
                c = conn.cursor()
                c.execute('SELECT material,name,uom FROM usage_products ORDER BY material')
                return [dict(r) for r in c.fetchall()]
            finally:
                conn.close()

    def add_usage_product(self, material: str, name: str, uom: str='', *, remote_first: bool=True):
        material = str(material or '').strip()
        name = str(name or material).strip()
        uom = str(uom or '').strip()
        if not material:
            raise RuntimeError('Material is required.')
        service = self._cloud_service()
        if remote_first and service is not None:
            try:
                service.upsert_usage_product(material, name, unit=uom)
                self.replace_usage_products(service.list_usage_products(force_refresh=True), preserve_pending=True)
                self._emit_usage_event('upsert', {'material': material, 'name': name, 'uom': uom, 'source': 'remote'})
                return {'status': 'remote', 'queued': False}
            except SERVICE_OPERATION_EXCEPTIONS as exc:
                if is_transient_remote_error(exc):
                    self.queue_usage_product_pending('upsert', material, name, uom)
                    self._upsert_usage_product_local(material, name, uom)
                    self._emit_usage_event('upsert', {'material': material, 'name': name, 'uom': uom, 'source': 'queued'})
                    return {'status': 'queued', 'queued': True}
                raise
        self._upsert_usage_product_local(material, name, uom)
        self._emit_usage_event('upsert', {'material': material, 'name': name, 'uom': uom, 'source': 'local'})
        return {'status': 'local', 'queued': False}

    def delete_usage_product(self, material: str, *, remote_first: bool=True):
        material = str(material or '').strip()
        if not material:
            return {'status': 'skipped', 'queued': False}
        service = self._cloud_service()
        if remote_first and service is not None:
            try:
                service.delete_usage_product_remote(material)
                self.replace_usage_products(service.list_usage_products(force_refresh=True), preserve_pending=True)
                self._emit_usage_event('delete', {'material': material, 'source': 'remote'})
                return {'status': 'remote', 'queued': False}
            except SERVICE_OPERATION_EXCEPTIONS as exc:
                if is_transient_remote_error(exc):
                    self.queue_usage_product_pending('delete', material, '', '')
                    self._delete_usage_product_local(material)
                    self._emit_usage_event('delete', {'material': material, 'source': 'queued'})
                    return {'status': 'queued', 'queued': True}
                raise
        self._delete_usage_product_local(material)
        self._emit_usage_event('delete', {'material': material, 'source': 'local'})
        return {'status': 'local', 'queued': False}

    def _upsert_usage_product_local(self, material: str, name: str, uom: str=''):
        with self._db_lock:
            conn = self._fresh_connection()
            try:
                c = conn.cursor()
                c.execute("\n                            INSERT OR REPLACE INTO usage_products(material,name,uom)\n                            VALUES(?,?,COALESCE(NULLIF(?,''),(SELECT uom FROM usage_products WHERE material=?),''))\n                            ", (material, name, uom, material))
                conn.commit()
            finally:
                conn.close()

    def _delete_usage_product_local(self, material: str):
        with self._db_lock:
            conn = self._fresh_connection()
            try:
                conn.execute('DELETE FROM usage_products WHERE material=?', (material,))
                conn.commit()
            finally:
                conn.close()

    def replace_usage_products(self, items, preserve_pending: bool=True):
        with self._db_lock:
            conn = self._fresh_connection()
            try:
                conn.execute('DELETE FROM usage_products')
                batch = []
                for it in items or []:
                    m = (it.get('material') or it.get('material_number') or it.get('material_code') or '').strip()
                    if not m:
                        continue
                    n = (it.get('name') or it.get('material_name') or m).strip()
                    u = (it.get('uom') or it.get('unit') or '').strip()
                    batch.append((m, n, u))
                if batch:
                    conn.executemany('INSERT OR REPLACE INTO usage_products(material,name,uom) VALUES(?,?,?)', batch)
                if preserve_pending:
                    pending = self._read_pending_usage_rows(conn)
                    for row in pending:
                        if str(row.get('op') or '').lower() == 'delete':
                            conn.execute('DELETE FROM usage_products WHERE material=?', (row.get('material'),))
                        else:
                            conn.execute('INSERT OR REPLACE INTO usage_products(material,name,uom) VALUES(?,?,?)', (row.get('material'), row.get('name') or row.get('material'), row.get('uom') or ''))
                conn.commit()
            finally:
                conn.close()

    def update_usage_uom_bulk(self, uom_map):
        if not uom_map:
            return
        with self._db_lock:
            conn = self._fresh_connection()
            try:
                cur = conn.cursor()
                for code, u in uom_map.items():
                    if not u:
                        continue
                    cur.execute("\nUPDATE usage_products\nSET uom=CASE WHEN IFNULL(uom,'')='' THEN ? ELSE uom END\nWHERE material=?\n", (u, code))
                conn.commit()
            finally:
                conn.close()
from runtime.shared.objects import safe_get
from runtime.shared.strings import normalize_text
from datetime import datetime

class UsagePendingRepositoryMixin:

    def queue_usage_product_pending(self, op: str, material: str, name: str='', uom: str=''):
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        op = 'delete' if str(op or '').strip().lower() == 'delete' else 'upsert'
        material = str(material or '').strip()
        if not material:
            return
        with self._db_lock:
            conn = self._fresh_connection()
            try:
                conn.execute('DELETE FROM usage_products_pending WHERE material=?', (material,))
                conn.execute('INSERT INTO usage_products_pending(op,material,name,uom,created_at) VALUES(?,?,?,?,?)', (op, material, str(name or '').strip(), str(uom or '').strip(), created_at))
                conn.commit()
            finally:
                conn.close()

    def pending_usage_changes_count(self) -> int:
        with self._db_lock:
            conn = self._fresh_connection()
            try:
                cur = conn.cursor()
                cur.execute('SELECT COUNT(*) AS cnt FROM usage_products_pending')
                row = cur.fetchone()
                return int(safe_get(row, 'cnt', 0) or 0)
            finally:
                conn.close()

    def _read_pending_usage_rows(self, conn=None):
        owns = conn is None
        conn = conn or self._fresh_connection()
        try:
            cur = conn.cursor()
            cur.execute('SELECT id,op,material,name,uom,created_at FROM usage_products_pending ORDER BY id ASC')
            return [dict(r) for r in cur.fetchall()]
        finally:
            if owns:
                conn.close()

    def _usage_change_payload(self, change: dict) -> dict:
        payload = change.get('payload') if isinstance(change.get('payload'), dict) else change
        payload = dict(payload or {})
        key = normalize_text(change.get('entity_key') or change.get('key'))
        if key:
            payload.setdefault('material', key)
            payload.setdefault('material_number', key)
            payload.setdefault('material_code', key)
        return payload
from runtime.application.dto import catalog_product_display_name
from runtime.application.dto import change_entity, change_operation
import threading
from runtime.shared.concurrency import wait_for_inflight_event

class UsageSynchronizationRepositoryMixin:

    def apply_remote_usage_changes(self, changes: list[dict]) -> dict:
        upserts = 0
        deletes = 0
        with self._db_lock:
            conn = self._fresh_connection()
            try:
                for change in changes or []:
                    if not isinstance(change, dict):
                        continue
                    entity = change_entity(change)
                    if entity and entity not in {'usage', 'usage_product', 'usage_products', 'catalog_usage'}:
                        continue
                    payload = self._usage_change_payload(change)
                    material = normalize_text(payload.get('material') or payload.get('material_number') or payload.get('material_code'))
                    if not material:
                        continue
                    if change_operation(change) == 'delete':
                        conn.execute('DELETE FROM usage_products WHERE material=?', (material,))
                        deletes += 1
                        continue
                    name = catalog_product_display_name(payload, material)
                    uom = normalize_text(payload.get('uom') or payload.get('unit') or payload.get('unit_of_measure'))
                    conn.execute("\nINSERT INTO usage_products(material,name,uom)\nVALUES(?,?,COALESCE(NULLIF(?,''),(SELECT uom FROM usage_products WHERE material=?),''))\nON CONFLICT(material) DO UPDATE SET\n  name=excluded.name,\n  uom=COALESCE(NULLIF(excluded.uom,''), usage_products.uom, '')\n", (material, name, uom, material))
                    upserts += 1
                conn.commit()
            finally:
                conn.close()
        if upserts or deletes:
            self._emit_usage_event('delta', {'upserts': upserts, 'deletes': deletes, 'source': 'server'})
        return {'upserts': upserts, 'deletes': deletes, 'applied': bool(upserts or deletes)}

    def refresh_usage_products_from_server(self, *, force_refresh: bool=True):
        service = self._cloud_service()
        if not service:
            return []
        if not force_refresh:
            existing_rows = self.fetch_usage_products()
            if existing_rows:
                logger.info('Returning cached usage products; no server refresh requested')
                return existing_rows
        now = datetime.now().timestamp()
        with self._db_lock:
            event = getattr(self, '_usage_refresh_event', None)
            if event is None:
                event = threading.Event()
                self._usage_refresh_event = event
                self._usage_refresh_started_at = now
                should_load = True
            else:
                should_load = False
        if not should_load:
            wait_for_inflight_event(event, timeout_seconds=8.0, logger_=logger, context='DatabaseUsageCatalogMixin.refresh_usage_products_from_server')
            with self._db_lock:
                cached_rows = list(getattr(self, '_usage_refresh_result', []) or [])
            if cached_rows:
                return cached_rows
            rows = self.fetch_usage_products()
            if rows:
                logger.info('Returning existing usage catalog rows while refresh is in flight')
                return rows
            logger.debug('Skipped duplicate usage catalog server refresh while another worker is loading')
            return []
        try:
            items = list(service.list_usage_products(force_refresh=force_refresh) or [])
            if not items:
                existing_rows = self.fetch_usage_products()
                with self._db_lock:
                    self._usage_refresh_result = list(existing_rows or [])
                self._emit_usage_event('refresh', {'count': len(existing_rows or []), 'source': 'server', 'preserved': True})
                logger.warning('Server returned an empty usage catalog; preserved %s local rows', len(existing_rows or []))
                return existing_rows
            self.replace_usage_products(items, preserve_pending=True)
            rows = self.fetch_usage_products()
            with self._db_lock:
                self._usage_refresh_result = list(rows or [])
            self._emit_usage_event('refresh', {'count': len(rows or []), 'source': 'server'})
            return rows
        finally:
            with self._db_lock:
                event = getattr(self, '_usage_refresh_event', None)
                self._usage_refresh_event = None
                self._usage_refresh_started_at = 0.0
                if event is not None:
                    event.set()

    def sync_pending_usage_changes(self):
        service = self._cloud_service()
        if not service:
            return {'synced': 0, 'remaining': self.pending_usage_changes_count()}
        with self._db_lock:
            conn = self._fresh_connection()
            try:
                rows = self._read_pending_usage_rows(conn)
                synced = 0
                for row in rows:
                    material = str(row.get('material') or '').strip()
                    op = str(row.get('op') or 'upsert').strip().lower()
                    if not material:
                        conn.execute('DELETE FROM usage_products_pending WHERE id=?', (row.get('id'),))
                        continue
                    try:
                        if op == 'delete':
                            service.delete_usage_product_remote(material)
                        else:
                            service.upsert_usage_product(material, str(row.get('name') or material), unit=str(row.get('uom') or ''))
                    except SERVICE_OPERATION_EXCEPTIONS as exc:
                        if is_transient_remote_error(exc):
                            break
                        conn.execute('DELETE FROM usage_products_pending WHERE id=?', (row.get('id'),))
                        continue
                    conn.execute('DELETE FROM usage_products_pending WHERE id=?', (row.get('id'),))
                    synced += 1
                conn.commit()
            finally:
                conn.close()
        return {'synced': synced, 'remaining': self.pending_usage_changes_count(), 'refreshed': False}

class DatabaseUsageCatalogMixin(UsageLocalRepositoryMixin, UsagePendingRepositoryMixin, UsageSynchronizationRepositoryMixin):
    """Composition surface for usage catalog persistence and synchronization."""
