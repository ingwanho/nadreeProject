"""One-time, approval-scoped hierarchy data repair. Defaults to read-only planning.

Run as the API service user, from the implementation root. This script does not
alter schemas, accounts, permissions, bookings, payments, or Firebase documents.
The apply mode is restricted to the explicitly approved test database.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import and_, select, text, update
from sqlalchemy.engine import make_url

from app.account_deletion_store import DeletionStore
from app.config import Settings
from app.db import Database, require_columns
from app.spot_hierarchy_repair import plan_repair


TABLES = ('MSP_ORG', 'MSP_REGION', 'MSP_LOCAL', 'MSP_SPOT', 'MSP_SPOT_MASTER', 'MSP_ADMIN_SPOT_SCOPE')
BACKUP_ROOT = Path('build/test-runtime/spot-hierarchy-repair-2026-11-10')
REFERENCE_COLUMNS = {
    'MSP_ADMIN': ('admin_id', 'contract_id', 'primary_spot_master_id', 'is_active'),
    'MSP_ADMIN_ROLE': ('admin_id', 'role_code', 'expires_at'),
    'MSP_SPOT_RENT': ('spot_master_id', 'legacy_spot_code', 'delivery_service_type', 'deletion_request_id'),
    'MSP_VEHICLE': ('vehicle_id', 'spot_master_id', 'is_active'),
    'MSP_RENTAL_VEHICLE': ('vehicle_id', 'model_id', 'price_type', 'premium_daily_price', 'rental_enabled'),
    'MSP_VEHICLE_STATUS': ('vehicle_id', 'status', 'maintenance_until'),
    'MSP_SENSOR': ('sensor_id', 'spot_master_id', 'vehicle_id', 'is_active'),
    'MSP_RESERVATION': ('reservation_id', 'spot_master_id', 'uid_token', 'reservation_status', 'assigned_vehicle_id', 'vehicle_assignment_status'),
    'MSP_RENTAL_CONTRACT': ('rental_contract_id', 'reservation_id', 'pickup_spot_master_id', 'return_spot_master_id', 'uid_token', 'contract_status'),
    'MSP_RENTAL_PAYMENT': ('payment_id', 'reservation_id', 'payment_status', 'refund_status', 'refunded_amount', 'paypal_order_id', 'paypal_capture_id'),
    'MSP_VEHICLE_QR': ('qr_id', 'vehicle_id', 'qr_status', 'qr_code_hash'),
    'MSP_RENTAL_TIER': ('spot_master_id', 'tier_type', 'min_cc', 'max_cc', 'price'),
    'MSP_SPOT_DELIVERY_REGION': ('spot_master_id', 'delivery_region_id'),
    'MSP_RESERVATION_HISTORY': None,
    'MSP_RENTAL_CONTRACT_HISTORY': None,
    'MSP_VEHICLE_QR_HISTORY': None,
    'MSP_RENTAL_ONSITE_REQUEST': None,
}


class RepairBlocked(RuntimeError):
    """A safe operator diagnostic without database bind values."""


def json_value(value):
    if isinstance(value, (datetime, date)):
        return {'type': type(value).__name__, 'value': value.isoformat()}
    if isinstance(value, Decimal):
        return {'type': 'Decimal', 'value': str(value)}
    raise TypeError(type(value).__name__)


def serialized(value):
    return json.dumps(value, default=json_value, sort_keys=True, ensure_ascii=True)


def reference_digests(connection, db):
    results = {}
    for name, wanted in REFERENCE_COLUMNS.items():
        table = db.table(name)
        if wanted is not None and any(key not in table.c for key in wanted):
            raise RepairBlocked('Reference schema cannot be verified: ' + name)
        columns = [table.c[key] for key in wanted] if wanted is not None else list(table.c)
        rows = [serialized(dict(row)) for row in connection.execute(select(*columns)).mappings()]
        results[name] = {'count': len(rows), 'digest': hashlib.sha256(serialized(sorted(rows)).encode()).hexdigest()}
    return results


def snapshot(connection, tables, lock=False):
    return {name: [dict(row) for row in connection.execute(
        select(table).order_by(*table.primary_key.columns).with_for_update() if lock
        else select(table).order_by(*table.primary_key.columns)).mappings()]
        for name, table in tables.items()}


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(serialized(value))
        stream.flush()
        os.fsync(stream.fileno())


def safe_summary(operations, problems):
    return {'operation_count': len(operations),
        'tables': dict(Counter(operation['table'] for operation in operations)),
        'inserts': sum(operation['before'] is None for operation in operations),
        'updates': sum(operation['before'] is not None for operation in operations),
        'problem_count': len(problems), 'problems': problems}


def run(apply):
    settings = Settings()
    url = settings.database_url.get_secret_value()
    if make_url(url).database != 'RIDERLOG_V2_DATA_TEST':
        raise RepairBlocked('Refusing an unapproved database')
    db = Database(url)
    tables = {name: db.table(name) for name in TABLES}
    # Reflect before obtaining any data locks; reflection must not wait on a
    # second connection while the first connection holds locks.
    for name in REFERENCE_COLUMNS:
        db.table(name)
    with db.engine.begin() as connection:
        if not apply:
            connection.execute(text('SET TRANSACTION READ ONLY'))
        original = snapshot(connection, tables, lock=apply)
        operations, problems = plan_repair(original)
        summary = safe_summary(operations, problems)
        summary['mode'] = 'apply' if apply else 'plan'
        summary['database'] = 'RIDERLOG_V2_DATA_TEST'
        summary['original_master_count'] = len(original['MSP_SPOT_MASTER'])
        if any(not row.get('unit_name') for row in original['MSP_SPOT_MASTER']):
            raise RepairBlocked('An existing master has no canonical unit_name')
        if problems:
            print(json.dumps(summary))
            raise RepairBlocked('Repair plan has unresolved structural problems')
        if not apply:
            summary['reference_tables_verified'] = len(reference_digests(connection, db))
            print(json.dumps(summary))
            return
        # Confirmation receipts and in-flight deletion requests contain the
        # old hierarchy scope. Never rewrite those snapshots to force a fit.
        if list(DeletionStore(settings).pending()):
            raise RepairBlocked('A privacy deletion request is still in progress')
        before_references = reference_digests(connection, db)
        os.umask(0o077)
        BACKUP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        if BACKUP_ROOT.stat().st_mode & 0o077:
            raise RepairBlocked('Backup directory must be private')
        backup_dir = BACKUP_ROOT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup_dir.mkdir(mode=0o700)
        private_json(backup_dir / 'before.json', original)
        private_json(backup_dir / 'operations.json', operations)
        private_json(backup_dir / 'reference-digests.json', before_references)
        for operation in operations:
            table = tables[operation['table']]
            key = operation['key']
            condition = and_(*(table.c[name] == value for name, value in key.items()))
            current = connection.execute(select(table).where(condition)).mappings().first()
            if (dict(current) if current else None) != operation['before']:
                raise RepairBlocked('Hierarchy changed after planning; transaction rolled back')
            require_columns(table, operation['values'])
            if operation['before'] is None:
                connection.execute(table.insert().values(**operation['values']))
            else:
                result = connection.execute(update(table).where(condition).values(**operation['values']))
                if result.rowcount != 1:
                    raise RepairBlocked('Repair did not update exactly one row')
        remaining, blockers = plan_repair(snapshot(connection, tables))
        if remaining or blockers:
            raise RepairBlocked('Hierarchy postcondition failed; transaction rolled back')
        after_references = reference_digests(connection, db)
        if after_references != before_references:
            raise RepairBlocked('Business reference preservation check failed; transaction rolled back')
        private_json(backup_dir / 'verified.json', {
            'summary': summary, 'remaining_operations': 0, 'remaining_problems': 0,
            'reference_digests_unchanged': True,
            'verified_at': datetime.now(timezone.utc),
        })
        summary['backup_directory'] = str(backup_dir)
        summary['remaining_operations'] = 0
        summary['reference_digests_unchanged'] = True
    summary['committed'] = True
    print(json.dumps(summary))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply the approved test database repair after private backups')
    arguments = parser.parse_args()
    try:
        run(arguments.apply)
    except Exception as exc:
        # SQL bind values, provider messages and settings must not reach logs.
        diagnostic = {'result': 'failed', 'exception_type': type(exc).__name__}
        if isinstance(exc, RepairBlocked):
            diagnostic['reason'] = str(exc)
        print(json.dumps(diagnostic))
        raise SystemExit(1)
