"""Persistent storage and idempotent, validated CSV ingestion."""
import csv
import hashlib
import io
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'datasets'
DEFAULT_DB = ROOT / 'data' / 'reconciliation.sqlite3'
SOURCE_TABLES = ['ingestion_batches','customers','bank_accounts','chart_of_accounts','users','orders',
                 'processor_transactions','processor_payouts','payout_items','bank_transactions','ledger_journals','ledger_entries']
SCHEMA = '''
CREATE INDEX IF NOT EXISTS ix_tx_order ON processor_transactions(order_id);
CREATE INDEX IF NOT EXISTS ix_items_payout ON payout_items(payout_id);
CREATE INDEX IF NOT EXISTS ix_journal_ref ON ledger_journals(reference);
CREATE INDEX IF NOT EXISTS ix_entry_journal ON ledger_entries(journal_id);
CREATE TABLE IF NOT EXISTS imports (
 id TEXT PRIMARY KEY, table_name TEXT NOT NULL, filename TEXT NOT NULL, checksum TEXT NOT NULL,
 created_at TEXT NOT NULL, inserted INTEGER NOT NULL, duplicates INTEGER NOT NULL, rejected INTEGER NOT NULL,
 raw_path TEXT NOT NULL, actor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rejected_rows (
 id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id), row_number INTEGER NOT NULL,
 reason TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, as_of_date TEXT NOT NULL,
 status TEXT NOT NULL, rule_version TEXT NOT NULL, input_fingerprint TEXT NOT NULL, summary TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS checks (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL, entity_id TEXT NOT NULL,
 status TEXT NOT NULL, reason TEXT NOT NULL, expected_cents INTEGER, actual_cents INTEGER, variance_cents INTEGER,
 currency TEXT NOT NULL, candidates TEXT NOT NULL, rule_id TEXT NOT NULL,
 UNIQUE(run_id,stage,entity_id));
CREATE INDEX IF NOT EXISTS ix_checks_run ON checks(run_id,stage,status);
CREATE TABLE IF NOT EXISTS allocations (
 id TEXT PRIMARY KEY, check_id TEXT NOT NULL REFERENCES checks(id), source_type TEXT NOT NULL,
 source_id TEXT NOT NULL, side TEXT NOT NULL, amount_cents INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_alloc_check ON allocations(check_id);
CREATE TABLE IF NOT EXISTS cases (
 id TEXT PRIMARY KEY, stage TEXT NOT NULL, entity_id TEXT NOT NULL, type TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open', assigned_to TEXT REFERENCES users(user_id),
 opened_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_check_id TEXT NOT NULL REFERENCES checks(id),
 finding_active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
 resolution TEXT, UNIQUE(stage,entity_id));
CREATE TABLE IF NOT EXISTS history (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), actor TEXT NOT NULL,
 action TEXT NOT NULL, created_at TEXT NOT NULL, note TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_history_case ON history(case_id,created_at);
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), source_path TEXT NOT NULL,
 source_record_id TEXT NOT NULL, note TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), bank_txn_id TEXT,
 actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, UNIQUE(case_id));
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id), expires_at TEXT NOT NULL);
'''


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return f'{prefix}-{uuid4().hex[:16]}'


def path():
    return Path(os.environ.get('RECON_DB', str(DEFAULT_DB)))


@contextmanager
def connect(write=False):
    database = path()
    database.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(database, timeout=60)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=60000')
    try:
        if write:
            c.execute('BEGIN IMMEDIATE')
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def initialize():
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        schema = (DATASETS / 'documentation/schema.sql').read_text().split('CREATE TABLE reconciliation_runs')[0]
        c.executescript(schema.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS '))
        c.executescript(SCHEMA)
        if 'active' not in [r['name'] for r in c.execute('PRAGMA table_info(decisions)')]:
            c.execute('ALTER TABLE decisions ADD COLUMN active INTEGER NOT NULL DEFAULT 1')


def rows(c, sql, args=()):
    return [dict(x) for x in c.execute(sql,args).fetchall()]


def metadata(c, table):
    if table not in SOURCE_TABLES:
        raise ValueError('Unsupported source table')
    return [dict(x) for x in c.execute(f'PRAGMA table_info({table})')]


def validate(table, r):
    if 'currency' in r and r['currency'] != 'USD':
        raise ValueError('Unsupported currency: this workspace accepts USD')
    if 'source_system' in r:
        expected = {'orders':'storefront','processor_transactions':'processor','processor_payouts':'processor',
                    'payout_items':'processor','bank_transactions':'bank','ledger_journals':'ledger','ledger_entries':'ledger'}[table]
        if r['source_system'] != expected:
            raise ValueError('Unexpected source-system namespace')
    for k,v in r.items():
        if k.endswith('_at') and v:
            dt=datetime.fromisoformat(v.replace('Z','+00:00'))
            if dt.tzinfo is None: raise ValueError(f'{k} requires a timezone')
        if k in ('value_date','posting_date','settlement_date','expected_arrival') and v:
            from datetime import date
            date.fromisoformat(v)
    statuses={'orders':{'paid','partially_paid','unpaid','authorized','cancelled'},
              'processor_transactions':{'succeeded','authorized'},'processor_payouts':{'paid','in_transit'},
              'bank_transactions':{'posted'},'ledger_journals':{'posted'}}
    if table in statuses and r['status'] not in statuses[table]:
        raise ValueError('Unsupported status')
    if table=='orders' and r['order_amount_cents']<=0: raise ValueError('Order amount must be positive')
    if table=='processor_transactions':
        signs={'capture':1,'fee':-1,'refund':-1,'chargeback':-1,'reserve_hold':-1,'reserve_release':1,'authorization':0}
        if r['type'] not in signs: raise ValueError('Unsupported processor event type')
        sign=signs[r['type']]
        if (sign and r['amount_cents']*sign<=0) or (not sign and r['amount_cents']!=0):
            raise ValueError('Amount sign does not agree with event type')
        if (r['type']=='authorization') != (r['status']=='authorized'):
            raise ValueError('Status does not agree with event type')
        if not sign and (r['authorized_amount_cents'] is None or r['authorized_amount_cents']<=0):
            raise ValueError('Authorization requires a positive authorized amount')
    if table=='payout_items':
        pass # Cross-record amount agreement is checked in the reconciliation engine.


def import_csv(table, content, filename, actor='system'):
    if len(content)>25*1024*1024: raise ValueError('Maximum CSV size is 25 MB')
    digest=hashlib.sha256(content).hexdigest()
    iid=uid('IMP')
    raw_dir=path().parent/'raw'
    raw_dir.mkdir(parents=True,exist_ok=True)
    raw_path=raw_dir/f'{digest}.csv'
    if not raw_path.exists(): raw_path.write_bytes(content)
    reader=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    inserted=duplicates=rejected=0
    with connect(write=True) as c:
        meta=metadata(c,table)
        fields=[x['name'] for x in meta]
        pk=next(x['name'] for x in meta if x['pk'])
        if reader.fieldnames is None or len(reader.fieldnames)!=len(set(reader.fieldnames)) or set(reader.fieldnames)!=set(fields):
            raise ValueError('CSV headers must match the selected source table exactly')
        c.execute('INSERT INTO imports VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (iid,table,Path(filename).name,digest,now(),0,0,0,str(raw_path.relative_to(path().parent)),actor))
        for line,raw in enumerate(reader,2):
            try:
                if None in raw or any(v is None for v in raw.values()): raise ValueError('Malformed CSV row')
                r={}
                for col in meta:
                    val=raw[col['name']]
                    if val=='': val=None
                    if val is None and (col['notnull'] or col['pk']): raise ValueError(f"Missing {col['name']}")
                    if val is not None and col['type'] in ('BIGINT','INTEGER'): val=int(val)
                    r[col['name']]=val
                validate(table,r)
                existing=c.execute(f'SELECT * FROM {table} WHERE {pk}=?',(r[pk],)).fetchone()
                if existing:
                    if dict(existing)!=r: raise ValueError('Existing identifier has conflicting contents; source records are immutable')
                    duplicates+=1
                    continue
                c.execute(f'INSERT INTO {table} ({",".join(fields)}) VALUES ({",".join("?" for _ in fields)})',[r[k] for k in fields])
                inserted+=1
            except (ValueError,sqlite3.IntegrityError) as e:
                rejected+=1
                c.execute('INSERT INTO rejected_rows VALUES (?,?,?,?,?)',(uid('REJ'),iid,line,str(e),json.dumps(raw)))
        c.execute('UPDATE imports SET inserted=?,duplicates=?,rejected=? WHERE id=?',(inserted,duplicates,rejected,iid))
    return dict(id=iid,inserted=inserted,duplicates=duplicates,rejected=rejected)


def seed():
    initialize()
    result=[]
    for table in SOURCE_TABLES:
        file=DATASETS/'source'/f'{table}.csv'
        result.append(dict(table=table,**import_csv(table,file.read_bytes(),file.name)))
    return result


def audit(c, case_id, actor, action, note):
    c.execute('INSERT INTO history VALUES (?,?,?,?,?,?)',(uid('EVT'),case_id,actor,action,now(),note))
