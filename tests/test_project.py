import csv
import io
import json
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import db,engine
from app.cli import evaluate
from app.main import app


@pytest.fixture(scope='session')
def baseline(tmp_path_factory):
    target=tmp_path_factory.mktemp('baseline')/'test.sqlite3'
    import os
    previous=os.environ.get('RECON_DB');os.environ['RECON_DB']=str(target)
    db.seed();engine.run()
    if previous is None: os.environ.pop('RECON_DB')
    else: os.environ['RECON_DB']=previous
    return target


@pytest.fixture
def workspace(baseline,tmp_path,monkeypatch):
    target=tmp_path/'workspace.sqlite3'
    shutil.copy2(baseline,target)
    monkeypatch.setenv('RECON_DB',str(target))
    monkeypatch.setenv('RECON_DEMO','1')
    return target


@pytest.fixture
def client(workspace):
    with TestClient(app) as c:
        assert c.post('/api/login',json={'user_id':'USER-02'}).status_code==200
        yield c


def find_case(client,stage,reason=None):
    items=client.get('/api/exceptions',params={'stage':stage,'limit':100}).json()['items']
    return next(x for x in items if reason is None or x['reason']==reason)


def detail(client,key): return client.get(f'/api/exceptions/{key}').json()


def action(client,key,kind,**values):
    case=detail(client,key)['case']
    payload=dict(version=case['version'],note='Checked source evidence')
    payload.update(values)
    return client.post(f'/api/exceptions/{key}/{kind}',json=payload)


def test_full_baseline_and_holdout(workspace):
    report=evaluate()
    assert report['all_passed'],report
    assert report['passed']==10360
    assert report['split_passes']=={'development':8298,'holdout':2062}
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM cases').fetchone()[0]==68
        assert not c.execute('PRAGMA foreign_key_check').fetchall()


def test_engine_does_not_read_ground_truth(workspace,monkeypatch):
    original=Path.open
    def guarded(self,*args,**kwargs):
        assert 'evaluation' not in self.parts
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'open',guarded)
    assert engine.run()['summary']['reconciled']==10040


def test_replay_and_quarantine(workspace):
    replay=db.DATASETS/'fixtures/replay/processor_transactions_replay.csv'
    result=db.import_csv('processor_transactions',replay.read_bytes(),replay.name)
    assert (result['inserted'],result['duplicates'],result['rejected'])==(0,100,0)
    invalid=db.DATASETS/'fixtures/invalid/processor_transactions_invalid.csv'
    result=db.import_csv('processor_transactions',invalid.read_bytes(),invalid.name)
    assert (result['inserted'],result['duplicates'],result['rejected'])==(0,0,4)
    assert evaluate()['all_passed']


def test_conflicting_sources_are_immutable(workspace):
    with (db.DATASETS/'source/orders.csv').open() as f:
        reader=csv.DictReader(f);record=next(reader);fields=reader.fieldnames
    record['order_amount_cents']=str(int(record['order_amount_cents'])+1)
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader();writer.writerow(record)
    result=db.import_csv('orders',out.getvalue().encode(),'conflict.csv')
    assert result['inserted']==0 and result['rejected']==1
    with db.connect() as c:
        assert c.execute('SELECT order_amount_cents FROM orders WHERE order_id=?',(record['order_id'],)).fetchone()[0]!=int(record['order_amount_cents'])


def test_sessions_roles_and_csrf(workspace):
    with TestClient(app) as c:
        assert c.get('/api/exceptions').status_code==401
        assert c.post('/api/login',json={'user_id':'USER-01'}).status_code==200
        assert c.post('/api/runs',json={}).status_code==403
        assert c.post('/api/login',json={'user_id':'USER-02'},headers={'origin':'https://untrusted.example'}).status_code==403
        case=find_case(c,'order_to_payment')
        assert action(c,case['id'],'status',status='resolved').status_code==403
        assert c.post('/api/logout').status_code==200
        assert c.get('/api/me').status_code==401


def test_notes_stale_writes_and_reruns(client):
    case=find_case(client,'order_to_payment');key=case['id'];version=case['version']
    assert action(client,key,'notes',note='Investigation persists across runs').status_code==200
    assert client.post(f'/api/exceptions/{key}/notes',json={'version':version,'note':'stale edit'}).status_code==409
    assert action(client,key,'assign',assigned_to='USER-01').status_code==200
    assert action(client,key,'status',status='in_review').status_code==200
    before=detail(client,key)
    assert client.post('/api/runs',json={}).status_code==200
    after=detail(client,key)
    assert after['case']['status']=='in_review'
    assert after['case']['assigned_to']=='USER-01'
    assert len(after['history'])==len(before['history'])
    assert any(x['note']=='Investigation persists across runs' for x in after['history'])
    assert client.get('/api/exceptions').json()['total']==68


def test_amendment_clears_finding_preserves_case(client):
    items=client.get('/api/exceptions',params={'stage':'payment_to_payout','limit':100}).json()['items']
    case=next(x for x in items if x['variance_cents']>0);key=case['id']
    assert action(client,key,'notes',note='Request missing settlement membership').status_code==200
    file=db.DATASETS/'fixtures/late_evidence/missing_payout_items.csv'
    response=client.post('/api/imports/payout_items',files={'file':(file.name,file.read_bytes(),'text/csv')})
    assert response.json()['inserted']==2
    assert client.post('/api/runs',json={}).status_code==200
    after=detail(client,key)
    assert after['case']['finding_active']==0
    assert after['case']['status']=='open'
    assert any(h['action']=='finding_changed' for h in after['history'])
    assert action(client,key,'status',status='resolved').status_code==200
    assert client.post('/api/runs',json={}).status_code==200
    assert detail(client,key)['case']['status']=='resolved'


def test_evidence_and_approval_guardrails(client):
    case=find_case(client,'payout_to_bank','missing_bank_reference');key=case['id']
    info=detail(client,key);candidate=info['check']['candidates'][0]
    def approve():
        v=detail(client,key)['case']['version']
        return client.post(f'/api/matches/{key}/approve',json={'version':v,'note':'Confirmed remittance evidence','bank_txn_id':candidate})
    assert approve().status_code==422
    assert action(client,key,'evidence',source_path='../build_datasets.py').status_code==422
    assert action(client,key,'evidence',source_path='source/bank_transactions.csv',source_record_id='DOES-NOT-EXIST').status_code==422
    assert action(client,key,'evidence',source_path='source/bank_transactions.csv',source_record_id=candidate).status_code==200
    assert action(client,key,'assign',assigned_to='USER-02').status_code==200
    assert approve().status_code==403
    assert action(client,key,'assign',assigned_to='USER-01').status_code==200
    assert approve().status_code==200
    assert detail(client,key)['case']['status']=='resolved'
    assert approve().status_code==409
    assert client.post('/api/runs',json={}).status_code==200
    assert detail(client,key)['case']['status']=='resolved'


def test_active_difference_requires_evidence(client):
    case=find_case(client,'order_to_payment');key=case['id']
    assert action(client,key,'status',status='resolved').status_code==422
    assert action(client,key,'evidence',source_path='source/orders.csv',source_record_id=case['entity_id']).status_code==200
    assert action(client,key,'status',status='resolved').status_code==200


def test_api_filters_export_and_pagination(client):
    assert client.get('/api/health').status_code==200
    assert client.get('/api/reconciliations/summary').json()['open_cases']==68
    assert client.get('/api/exceptions',params={'stage':'order_to_payment'}).json()['total']==50
    assert len(client.get('/api/checks',params={'limit':5,'offset':10}).json()['items'])==5
    assert client.get('/api/checks',params={'limit':-1}).status_code==422
    assert client.get('/api/sources/not-a-table').status_code==404
    assert client.get('/api/exceptions/not-a-case').status_code==404
    assert 'text/csv' in client.get('/api/exports/exceptions.csv').headers['content-type']
    assert client.get('/api/runs').json()[0]['status']=='completed'


def test_import_upload_limits_and_headers(client):
    assert client.post('/api/imports/orders',files={'file':('wrong.csv',b'foo,bar\n1,2\n')}).status_code==422
    assert client.post('/api/imports/not-a-table',files={'file':('wrong.csv',b'foo\n')}).status_code==422
    file=db.DATASETS/'fixtures/invalid/processor_transactions_invalid.csv'
    r=client.post('/api/imports/processor_transactions',files={'file':(file.name,file.read_bytes())}).json()
    assert r['rejected']==4
    assert len(client.get(f'/api/imports/{r["id"]}/rejections').json())==4


def test_bank_is_never_reused_within_stage(workspace):
    with db.connect() as c:
        run=c.execute("SELECT id FROM runs WHERE status='completed' ORDER BY started_at DESC LIMIT 1").fetchone()[0]
        repeated=c.execute("SELECT a.source_id FROM allocations a JOIN checks ch ON ch.id=a.check_id WHERE ch.run_id=? AND ch.stage='payout_to_bank' AND ch.status='reconciled' AND a.source_type='bank_transactions' GROUP BY a.source_id HAVING COUNT(*)>1",(run,)).fetchall()
        assert not repeated


def test_authentication_can_disable_demo(workspace,monkeypatch):
    monkeypatch.setenv('RECON_DEMO','0');monkeypatch.setenv('RECON_PASSWORD','test-password-only')
    with TestClient(app) as c:
        assert c.get('/api/demo-users').status_code==404
        assert c.post('/api/login',json={'user_id':'USER-02'}).status_code==401
        assert c.post('/api/login',json={'user_id':'USER-02','password':'test-password-only'}).status_code==200


def test_imported_raw_file_can_support_case(client):
    case=find_case(client,'order_to_payment')
    with db.connect() as c:
        imported=c.execute("SELECT raw_path FROM imports WHERE table_name='orders' LIMIT 1").fetchone()[0]
    # Isolated test database shares the canonical data but needs a retained raw file of its own.
    target=db.path().parent/imported;target.parent.mkdir(exist_ok=True)
    target.write_bytes((db.DATASETS/'source/orders.csv').read_bytes())
    assert any(x['path']==imported for x in client.get('/api/evidence-files').json())
    assert action(client,case['id'],'evidence',source_path=imported,source_record_id=case['entity_id']).status_code==200


def test_changed_finding_reopens_case(client):
    case=find_case(client,'order_to_payment');key=case['id']
    assert action(client,key,'evidence',source_path='source/orders.csv',source_record_id=case['entity_id']).status_code==200
    assert action(client,key,'status',status='resolved').status_code==200
    with db.connect(write=True) as c:
        order=c.execute('SELECT * FROM orders WHERE order_id=?',(case['entity_id'],)).fetchone()
        template=dict(c.execute("SELECT * FROM processor_transactions WHERE type='capture' LIMIT 1").fetchone())
        template.update(txn_id='TXN-NEW-PARTIAL',order_id=case['entity_id'],amount_cents=1000,
                        related_txn_id=None,processed_at=order['ordered_at'],source_created_at=order['ordered_at'])
        c.execute('INSERT INTO processor_transactions VALUES ('+','.join('?' for _ in template)+')',list(template.values()))
    engine.run()
    result=detail(client,key)
    assert result['case']['status']=='open'
    assert any(x['action']=='reopened' for x in result['history'])
    assert result['attachments']


def test_changed_approved_match_requires_new_decision(client):
    case=find_case(client,'payout_to_bank','missing_bank_reference');key=case['id']
    candidate=detail(client,key)['check']['candidates'][0]
    assert action(client,key,'evidence',source_path='source/bank_transactions.csv',source_record_id=candidate).status_code==200
    def approve():
        return client.post(f'/api/matches/{key}/approve',json={'version':detail(client,key)['case']['version'],
            'note':'Verified original credit','bank_txn_id':candidate})
    assert approve().status_code==200
    with db.connect(write=True) as c:
        bank=dict(c.execute('SELECT * FROM bank_transactions WHERE bank_txn_id=?',(candidate,)).fetchone())
        bank['bank_txn_id']='BTX-NEW-CANDIDATE'
        c.execute('INSERT INTO bank_transactions VALUES ('+','.join('?' for _ in bank)+')',list(bank.values()))
    engine.run()
    result=detail(client,key)
    assert result['case']['status']=='open'
    assert result['decision'][0]['active']==0
    assert approve().status_code==200
    assert len([x for x in detail(client,key)['history'] if x['action']=='match_approved'])==2


def test_grouped_credit_allocation_and_ambiguity(client):
    from scripts.demo_scenarios import add_grouped_credit, add_grouped_payouts

    add_grouped_payouts()
    add_grouped_credit('BTX-DEMO-GROUP')
    run_id = engine.run()['id']
    with db.connect() as connection:
        allocations = db.rows(connection, """SELECT a.amount_cents FROM allocations a
            JOIN checks ch ON ch.id=a.check_id WHERE ch.run_id=?
            AND ch.status='reconciled' AND ch.stage='payout_to_bank'
            AND a.source_id='BTX-DEMO-GROUP' AND a.side='actual'""", (run_id,))
    assert sorted(row['amount_cents'] for row in allocations) == [40000, 60000]
    trace = client.get('/api/traces/PO-DEMO-A').json()
    assert trace['settlement']['actual_cents'] == 60000
    assert trace['credits'][0]['record']['amount_cents'] == 100000

    add_grouped_credit('BTX-DEMO-DUPLICATE')
    engine.run()
    for payout in ('PO-DEMO-A', 'PO-DEMO-B'):
        trace = client.get(f'/api/traces/{payout}').json()
        assert trace['settlement']['status'] == 'review'
        assert trace['settlement']['actual_cents'] is None


def test_late_credit_clears_finding_and_preserves_case(client):
    from scripts.demo_scenarios import add_late_deposit

    case = next(row for row in client.get('/api/exceptions', params={'search': 'PO-0011'}).json()['items']
                if row['stage'] == 'payout_to_bank')
    assert case['finding_active']
    add_late_deposit()
    engine.run()
    updated = detail(client, case['id'])
    assert not updated['case']['finding_active']
    assert updated['case']['status'] == 'open'
    assert any(event['action'] == 'finding_changed' for event in updated['history'])
