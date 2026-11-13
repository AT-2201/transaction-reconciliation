"""FastAPI workbench API, session permissions, and built dashboard hosting."""
import csv
import hashlib
import io
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request, Response, Depends, UploadFile, File, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import db, engine


@asynccontextmanager
async def lifespan(app):
    db.initialize()
    yield


app=FastAPI(title='Reconcile API',version='1.0.0',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=os.environ.get('RECON_ALLOWED_HOSTS','localhost,127.0.0.1,testserver').split(','))


@app.middleware('http')
async def same_origin(request, call_next):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and urlparse(origin).netloc!=request.headers.get('host'):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Cross-origin mutations are not allowed'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    if request.url.path.startswith('/api'): response.headers['Cache-Control']='no-store'
    return response


def actor(request: Request):
    token=request.cookies.get('recon_session','')
    with db.connect() as c:
        user=c.execute('SELECT u.* FROM sessions s JOIN users u ON u.user_id=s.user_id WHERE token_hash=? AND expires_at>?',
                       (hashlib.sha256(token.encode()).hexdigest(),db.now())).fetchone()
    if not user: raise HTTPException(401,'Sign in to the demo workspace')
    return dict(user)


def approver(user=Depends(actor)):
    if user['role']!='approver': raise HTTPException(403,'An approver is required for this action')
    return user


class Login(BaseModel):
    user_id: str
    password: str=''


@app.get('/api/health')
def health():
    return {'status':'ok','demo':os.environ.get('RECON_DEMO','1')=='1'}


@app.get('/api/demo-users')
def demo_users():
    if os.environ.get('RECON_DEMO','1')!='1': raise HTTPException(404)
    with db.connect() as c: return db.rows(c,'SELECT user_id,display_name,role FROM users')


@app.post('/api/login')
def login(body: Login,response: Response):
    demo=os.environ.get('RECON_DEMO','1')=='1'
    password=os.environ.get('RECON_PASSWORD')
    if not demo and (not password or not secrets.compare_digest(body.password,password)):
        raise HTTPException(401,'Invalid credentials')
    with db.connect(write=True) as c:
        user=c.execute('SELECT * FROM users WHERE user_id=?',(body.user_id,)).fetchone()
        if not user: raise HTTPException(401,'Unknown workspace user')
        token=secrets.token_urlsafe(32)
        expires=(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat()
        c.execute('DELETE FROM sessions WHERE expires_at<?',(db.now(),))
        c.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),body.user_id,expires))
    response.set_cookie('recon_session',token,httponly=True,samesite='strict',max_age=8*3600,
                        secure=os.environ.get('RECON_SECURE_COOKIES','0')=='1')
    return dict(user)


@app.get('/api/me')
def me(user=Depends(actor)): return user


@app.post('/api/logout')
def logout(request: Request,response: Response,user=Depends(actor)):
    with db.connect(write=True) as c:
        c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(request.cookies.get('recon_session','').encode()).hexdigest(),))
    response.delete_cookie('recon_session')
    return {'ok':True}


def latest(c):
    return c.execute("SELECT * FROM runs WHERE status='completed' ORDER BY started_at DESC LIMIT 1").fetchone()


@app.get('/api/reconciliations/summary')
def summary(user=Depends(actor)):
    with db.connect() as c:
        run=latest(c)
        stages=db.rows(c,'SELECT stage,status,COUNT(*) count FROM checks WHERE run_id=? GROUP BY stage,status',(run['id'],)) if run else []
        totals=db.rows(c,'SELECT status,COUNT(*) count FROM checks WHERE run_id=? GROUP BY status',(run['id'],)) if run else []
        workload=c.execute("SELECT COUNT(*) count,COALESCE(SUM(ABS(ch.variance_cents)),0) amount FROM cases x JOIN checks ch ON ch.id=x.last_check_id WHERE x.status NOT IN ('resolved','dismissed')").fetchone()
        trend=db.rows(c,"SELECT p.settlement_date,COUNT(*) payouts,SUM(p.net_amount_cents) expected_cents FROM processor_payouts p GROUP BY p.settlement_date ORDER BY p.settlement_date")
        overview={x['status']:x['count'] for x in totals}
        top=db.rows(c,"SELECT x.type,COUNT(*) count FROM cases x WHERE x.status NOT IN ('resolved','dismissed') GROUP BY x.type ORDER BY count DESC")
        return dict(run=dict(run) if run else None,stages=stages,counts=overview,open_cases=workload['count'],
                    flagged_variance_cents=workload['amount'],trend=trend,exception_types=top,
                    source_counts={table:c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in db.SOURCE_TABLES},
                    users=db.rows(c,'SELECT * FROM users'))


CASE_SELECT='''SELECT x.*,ch.reason,ch.expected_cents,ch.actual_cents,ch.variance_cents,ch.currency,
 ch.status AS check_status, u.display_name AS owner FROM cases x JOIN checks ch ON ch.id=x.last_check_id
 LEFT JOIN users u ON u.user_id=x.assigned_to'''


@app.get('/api/exceptions')
def exceptions(status: str='',stage: str='',search: str='',assigned_to: str='',
               offset: int=Query(0,ge=0),limit: int=Query(25,ge=1,le=100),user=Depends(actor)):
    where=[]; args=[]
    if status=='active': where.append("x.status NOT IN ('resolved','dismissed')")
    elif status: where.append('x.status=?'); args.append(status)
    if stage: where.append('x.stage=?'); args.append(stage)
    if assigned_to: where.append('x.assigned_to=?'); args.append(assigned_to)
    if search:
        where.append('(x.id LIKE ? OR x.entity_id LIKE ? OR x.type LIKE ?)')
        args.extend([f'%{search}%']*3)
    clause=' WHERE '+' AND '.join(where) if where else ''
    with db.connect() as c:
        total=c.execute('SELECT COUNT(*) FROM cases x'+clause,args).fetchone()[0]
        items=db.rows(c,CASE_SELECT+clause+' ORDER BY CASE WHEN x.status IN (\'resolved\',\'dismissed\') THEN 1 ELSE 0 END,ABS(COALESCE(ch.variance_cents,0)) DESC,x.opened_at LIMIT ? OFFSET ?',args+[limit,offset])
    return dict(items=items,total=total,offset=offset,limit=limit)


def case_row(c,case_id):
    row=c.execute(CASE_SELECT+' WHERE x.id=?',(case_id,)).fetchone()
    if not row: raise HTTPException(404,'Case not found')
    return dict(row)


@app.get('/api/exceptions/{case_id}')
def case_detail(case_id: str,user=Depends(actor)):
    with db.connect() as c:
        case=case_row(c,case_id)
        check=dict(c.execute('SELECT * FROM checks WHERE id=?',(case['last_check_id'],)).fetchone())
        check['candidates']=json.loads(check['candidates'])
        stage,key=case['stage'],case['entity_id']
        evidence={}
        if stage=='order_to_payment':
            evidence['orders']=db.rows(c,'SELECT * FROM orders WHERE order_id=?',(key,))
            evidence['processor_transactions']=db.rows(c,'SELECT * FROM processor_transactions WHERE order_id=? ORDER BY processed_at',(key,))
        elif stage in ('payment_to_payout','payout_to_bank'):
            evidence['processor_payouts']=db.rows(c,'SELECT * FROM processor_payouts WHERE payout_id=?',(key,))
            evidence['payout_items']=db.rows(c,'SELECT p.*,t.type,t.amount_cents,t.order_id FROM payout_items p JOIN processor_transactions t ON t.txn_id=p.txn_id WHERE p.payout_id=? ORDER BY p.txn_id',(key,))
            ids=check['candidates'] if stage=='payout_to_bank' else []
            evidence['bank_transactions']=db.rows(c,f'SELECT * FROM bank_transactions WHERE bank_txn_id IN ({",".join("?" for _ in ids)})',ids) if ids else []
        else:
            evidence['bank_transactions']=db.rows(c,'SELECT * FROM bank_transactions WHERE bank_txn_id=?',(key,))
            evidence['ledger_entries']=db.rows(c,'SELECT e.*,j.reference,j.posting_date FROM ledger_journals j JOIN ledger_entries e ON e.journal_id=j.journal_id WHERE j.reference=?',(key,))
        return dict(case=case,check=check,evidence=evidence,
            history=db.rows(c,'SELECT h.*,u.display_name actor_name FROM history h LEFT JOIN users u ON u.user_id=h.actor WHERE case_id=? ORDER BY created_at DESC',(case_id,)),
            attachments=db.rows(c,'SELECT * FROM evidence WHERE case_id=? ORDER BY created_at DESC',(case_id,)),
            decision=db.rows(c,'SELECT * FROM decisions WHERE case_id=?',(case_id,)))


class Note(BaseModel):
    note: str=Field(min_length=1,max_length=4000)
    version: int=Field(ge=1)

    @field_validator('note')
    @classmethod
    def meaningful_note(cls,value):
        if not value.strip(): raise ValueError('A reason is required')
        return value.strip()


class Action(Note):
    status: str|None=None
    assigned_to: str|None=None
    bank_txn_id: str|None=None
    source_path: str|None=None
    source_record_id: str=''


def check_version(c,case_id,version):
    row=case_row(c,case_id)
    if row['version']!=version: raise HTTPException(409,'Case changed. Refresh it before saving.')
    return row


def bump(c,case_id):
    c.execute('UPDATE cases SET updated_at=?,version=version+1 WHERE id=?',(db.now(),case_id))


@app.post('/api/exceptions/{case_id}/notes')
def note(case_id: str,body: Note,user=Depends(actor)):
    if not body.note.strip(): raise HTTPException(422,'Enter a note')
    with db.connect(write=True) as c:
        check_version(c,case_id,body.version)
        db.audit(c,case_id,user['user_id'],'note',body.note.strip()); bump(c,case_id)
    return {'ok':True}


@app.post('/api/exceptions/{case_id}/assign')
def assign(case_id: str,body: Action,user=Depends(actor)):
    with db.connect(write=True) as c:
        check_version(c,case_id,body.version)
        if body.assigned_to and not c.execute('SELECT 1 FROM users WHERE user_id=?',(body.assigned_to,)).fetchone():
            raise HTTPException(422,'Unknown assignee')
        c.execute('UPDATE cases SET assigned_to=? WHERE id=?',(body.assigned_to,case_id))
        db.audit(c,case_id,user['user_id'],'assigned',f'{body.assigned_to or "Unassigned"}: {body.note}'); bump(c,case_id)
    return {'ok':True}


@app.post('/api/exceptions/{case_id}/status')
def change_status(case_id: str,body: Action,user=Depends(actor)):
    allowed={'open','in_review','awaiting_evidence','resolved','dismissed'}
    if body.status not in allowed: raise HTTPException(422,'Unknown case status')
    if not body.note.strip(): raise HTTPException(422,'A reason is required')
    if body.status in ('resolved','dismissed') and user['role']!='approver': raise HTTPException(403,'An approver must close cases')
    with db.connect(write=True) as c:
        case=check_version(c,case_id,body.version)
        if body.status=='resolved' and case['finding_active'] and not c.execute('SELECT 1 FROM evidence WHERE case_id=?',(case_id,)).fetchone():
            raise HTTPException(422,'Attach supporting evidence before resolving an active difference')
        c.execute('UPDATE cases SET status=?,resolution=? WHERE id=?',(body.status,body.note if body.status in ('resolved','dismissed') else None,case_id))
        db.audit(c,case_id,user['user_id'],'status_changed',f'{case["status"]} → {body.status}: {body.note}'); bump(c,case_id)
    return {'ok':True}


@app.post('/api/exceptions/{case_id}/evidence')
def evidence(case_id: str,body: Action,user=Depends(actor)):
    if not body.source_path: raise HTTPException(422,'Select a source file')
    requested=Path(body.source_path)
    if requested.is_absolute() or '..' in requested.parts or not requested.parts:
        raise HTTPException(422,'Select a workspace evidence file')
    if requested.parts[0]=='raw':
        file=(db.path().parent/requested).resolve()
        with db.connect() as c:
            registered=c.execute('SELECT 1 FROM imports WHERE raw_path=?',(str(requested),)).fetchone()
        valid=registered and file.is_relative_to((db.path().parent/'raw').resolve())
    else:
        file=(db.DATASETS/requested).resolve()
        valid=requested.parts[0] in ('source','fixtures') and file.is_relative_to(db.DATASETS.resolve())
    if not valid or not file.is_file():
        raise HTTPException(422,'Evidence must reference a registered source file')
    with db.connect(write=True) as c:
        check_version(c,case_id,body.version)
        if body.source_record_id:
            with file.open(newline='') as stream:
                if not any(body.source_record_id in row.values() for row in csv.DictReader(stream)):
                    raise HTTPException(422,'Record was not found in that evidence file')
        c.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?)',(db.uid('EVD'),case_id,str(requested),body.source_record_id,body.note,user['user_id'],db.now()))
        db.audit(c,case_id,user['user_id'],'evidence_attached',f'{requested}: {body.note}'); bump(c,case_id)
    return {'ok':True}


@app.get('/api/evidence-files')
def evidence_files(user=Depends(actor)):
    files=[dict(path=str(p.relative_to(db.DATASETS)),label=str(p.relative_to(db.DATASETS)))
           for folder in ['source','fixtures/late_evidence'] for p in sorted((db.DATASETS/folder).glob('*.csv'))]
    with db.connect() as c:
        imported=db.rows(c,'SELECT raw_path,MIN(filename) filename FROM imports GROUP BY raw_path')
    files.extend(dict(path=x['raw_path'],label=f"Imported: {x['filename']} ({Path(x['raw_path']).stem[:8]})") for x in imported)
    return files


@app.post('/api/matches/{case_id}/approve')
def approve(case_id: str,body: Action,user=Depends(approver)):
    if not body.note.strip(): raise HTTPException(422,'Approval reason is required')
    with db.connect(write=True) as c:
        case=check_version(c,case_id,body.version)
        check=c.execute('SELECT * FROM checks WHERE id=?',(case['last_check_id'],)).fetchone()
        if case['stage']!='payout_to_bank' or check['status']!='review':
            raise HTTPException(422,'Only a proposed payout-to-bank match can be approved')
        if check['reason']=='ambiguous_grouped_bank_credit':
            raise HTTPException(422,'Correct the shared reference or deposit in the source records and rerun reconciliation')
        if body.bank_txn_id not in json.loads(check['candidates']): raise HTTPException(422,'Choose a proposed bank candidate')
        if case['assigned_to']==user['user_id']: raise HTTPException(403,'The case owner cannot approve their own match')
        if not c.execute('SELECT 1 FROM evidence WHERE case_id=?',(case_id,)).fetchone():
            raise HTTPException(422,'Attach source evidence before approving')
        existing=c.execute('SELECT 1 FROM decisions WHERE case_id=? AND active=1',(case_id,)).fetchone()
        if existing: raise HTTPException(409,'This case already has a recorded approval')
        used=c.execute('SELECT 1 FROM decisions WHERE bank_txn_id=? AND active=1',(body.bank_txn_id,)).fetchone()
        automatic=c.execute("SELECT 1 FROM allocations a JOIN checks ch ON ch.id=a.check_id WHERE ch.run_id=? AND ch.stage='payout_to_bank' AND ch.status='reconciled' AND a.source_type='bank_transactions' AND a.source_id=?",(check['run_id'],body.bank_txn_id)).fetchone()
        if used or automatic: raise HTTPException(409,'Bank credit is already allocated')
        c.execute('''INSERT INTO decisions VALUES (?,?,?,?,?,?,1) ON CONFLICT(case_id) DO UPDATE SET
            id=excluded.id,bank_txn_id=excluded.bank_txn_id,actor=excluded.actor,reason=excluded.reason,
            created_at=excluded.created_at,active=1''',(db.uid('DEC'),case_id,body.bank_txn_id,user['user_id'],body.note,db.now()))
        c.execute("UPDATE cases SET status='resolved',resolution=? WHERE id=?",(body.note,case_id))
        db.audit(c,case_id,user['user_id'],'match_approved',f'{body.bank_txn_id}: {body.note}'); bump(c,case_id)
    return {'ok':True}


class RunRequest(BaseModel):
    as_of_date: str='2026-11-05'


@app.post('/api/runs')
def run(body: RunRequest,user=Depends(approver)):
    from datetime import date
    try: date.fromisoformat(body.as_of_date)
    except ValueError: raise HTTPException(422,'Use an ISO date')
    return engine.run(body.as_of_date)


@app.get('/api/runs')
def runs(user=Depends(actor)):
    with db.connect() as c: return db.rows(c,'SELECT * FROM runs ORDER BY started_at DESC LIMIT 50')


@app.get('/api/runs/{run_id}')
def run_detail(run_id: str,user=Depends(actor)):
    with db.connect() as c:
        result=c.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
        if not result: raise HTTPException(404,'Run not found')
        return dict(run=dict(result),stages=db.rows(c,'SELECT stage,status,COUNT(*) count FROM checks WHERE run_id=? GROUP BY stage,status',(run_id,)))


@app.get('/api/checks')
def checks(stage: str='',status: str='',search: str='',offset: int=Query(0,ge=0),limit: int=Query(50,ge=1,le=100),user=Depends(actor)):
    with db.connect() as c:
        run=latest(c)
        if not run: return dict(items=[],total=0)
        where='run_id=?'; args=[run['id']]
        for col,val in [('stage',stage),('status',status)]:
            if val: where+=f' AND {col}=?'; args.append(val)
        if search: where+=' AND entity_id LIKE ?'; args.append(f'%{search}%')
        total=c.execute('SELECT COUNT(*) FROM checks WHERE '+where,args).fetchone()[0]
        return dict(items=db.rows(c,'SELECT * FROM checks WHERE '+where+' ORDER BY entity_id LIMIT ? OFFSET ?',args+[limit,offset]),total=total)


@app.get('/api/traces/{payout_id}')
def payout_trace(payout_id: str, user=Depends(actor)):
    with db.connect() as c:
        run = latest(c)
        if not run:
            raise HTTPException(404, 'Run reconciliation first')
        checks = db.rows(c, """SELECT * FROM checks WHERE run_id=? AND entity_id=?
            AND stage IN ('payment_to_payout','payout_to_bank')""", (run['id'], payout_id))
        if not checks:
            raise HTTPException(404, 'Payout absent from the latest run')
        composition = next(check for check in checks if check['stage']=='payment_to_payout')
        settlement = next(check for check in checks if check['stage']=='payout_to_bank')
        components = db.rows(c, """SELECT t.type, COUNT(*) count, SUM(a.amount_cents) amount
            FROM allocations a JOIN processor_transactions t ON t.txn_id=a.source_id
            WHERE a.check_id=? AND a.side='actual' GROUP BY t.type ORDER BY t.type""", (composition['id'],))
        credits = []
        for credit_id in json.loads(settlement['candidates']):
            credit = c.execute('SELECT * FROM bank_transactions WHERE bank_txn_id=?', (credit_id,)).fetchone()
            if credit is None:
                continue
            ledger = c.execute("SELECT * FROM checks WHERE run_id=? AND stage='bank_to_ledger' AND entity_id=?",
                               (run['id'], credit_id)).fetchone()
            credits.append(dict(record=dict(credit), ledger=dict(ledger) if ledger else None))
        return dict(payout_id=payout_id, composition=composition, components=components,
                    settlement=settlement, credits=credits)


@app.get('/api/imports')
def imports(user=Depends(actor)):
    with db.connect() as c: return db.rows(c,'SELECT * FROM imports ORDER BY created_at DESC LIMIT 100')


@app.get('/api/imports/{import_id}/rejections')
def rejections(import_id: str,user=Depends(actor)):
    with db.connect() as c: return db.rows(c,'SELECT * FROM rejected_rows WHERE import_id=? ORDER BY row_number LIMIT 100',(import_id,))


@app.post('/api/imports/{table}')
def import_file(table: str,file: UploadFile=File(...),user=Depends(approver)):
    if table not in db.SOURCE_TABLES: raise HTTPException(422,'Unsupported source table')
    content=file.file.read(25*1024*1024+1)
    try: return db.import_csv(table,content,file.filename or 'upload.csv',user['user_id'])
    except (ValueError,UnicodeError) as e: raise HTTPException(422,str(e))


@app.get('/api/sources/{table}')
def source(table: str,offset: int=Query(0,ge=0),limit: int=Query(25,ge=1,le=100),user=Depends(actor)):
    if table not in db.SOURCE_TABLES: raise HTTPException(404,'Unknown source')
    with db.connect() as c:
        return dict(columns=[x['name'] for x in db.metadata(c,table)],
                    items=db.rows(c,f'SELECT * FROM {table} LIMIT ? OFFSET ?',(limit,offset)),
                    total=c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])


@app.get('/api/exports/exceptions.csv')
def export(user=Depends(actor)):
    with db.connect() as c: data=db.rows(c,CASE_SELECT+' ORDER BY x.id')
    stream=io.StringIO()
    fields=['id','stage','entity_id','type','status','owner','expected_cents','actual_cents','variance_cents','currency','opened_at','resolution']
    writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore'); writer.writeheader()
    for row in data:
        # Prevent spreadsheet formula execution in reviewer-provided text.
        writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for k,v in row.items()})
    return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="reconciliation-exceptions.csv"'})


DIST=db.ROOT/'frontend/dist'
if DIST.exists():
    app.mount('/assets',StaticFiles(directory=DIST/'assets'),name='assets')
    @app.get('/favicon.svg',include_in_schema=False)
    def favicon(): return FileResponse(DIST/'favicon.svg')
    @app.get('/')
    def index(): return FileResponse(DIST/'index.html')
