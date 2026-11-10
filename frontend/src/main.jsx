import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, ArrowRight, ArrowUpRight, BookOpen, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Clock3, Download, FileCheck2, FileText, GitBranch, LoaderCircle, LogOut, Play, Plus, Search, ShieldCheck, Upload, X} from 'lucide-react';
import './styles.css';
import demoContext from '../../datasets/demo_context.json';
import {demoApi, exceptionExport, publicDemo} from './public-demo';

const STAGES={order_to_payment:'Order → payment',payment_to_payout:'Payment → payout',payout_to_bank:'Payout → bank',bank_to_ledger:'Bank → ledger'};
const STATUS={reconciled:'Reconciled',exception:'Exception',review:'Needs review',pending:'Pending',partial:'Partial',not_eligible:'Not eligible',open:'Open',in_review:'In review',awaiting_evidence:'Awaiting evidence',resolved:'Resolved',dismissed:'Dismissed'};
const money=(n)=>n==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/100);
const number=n=>new Intl.NumberFormat('en-US').format(n||0);
const human=s=>(s||'').replaceAll('_',' ').replace(/\b\w/g,x=>x.toUpperCase());
const datetime=s=>s?new Date(s).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'—';

async function api(path,options={}){
  if(publicDemo)return demoApi(path,options);
  const response=await fetch('/api'+path,{credentials:'same-origin',...options,headers:options.body instanceof FormData?{}:{'Content-Type':'application/json',...options.headers}});
  const data=await response.json().catch(()=>({}));
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Please check the values and try again.');
  return data;
}
function Badge({status}){return <span className={'badge '+status}><i/>{STATUS[status]||human(status)}</span>}
function Empty({title='Nothing here yet',text='Your results will appear here.'}){return <div className="empty"><FileCheck2 size={32}/><h3>{title}</h3><p>{text}</p></div>}
function Loading(){return <div className="loading"><LoaderCircle className="spin" size={23}/> Loading workspace…</div>}
function Pagination({page,total,size,onChange}){return <div className="pagination"><span>{total?`${number(page*size+1)}–${number(Math.min((page+1)*size,total))} of ${number(total)}`:'0 results'}</span><div><button className="icon-button" aria-label="Previous page" disabled={!page} onClick={()=>onChange(page-1)}><ChevronLeft size={17}/></button><button className="icon-button" aria-label="Next page" disabled={(page+1)*size>=total} onClick={()=>onChange(page+1)}><ChevronRight size={17}/></button></div></div>}

function LoginScreen({onLogin}){
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[password,setPassword]=useState('');
 async function login(user_id){setBusy(true);setError('');try{onLogin(await api('/login',{method:'POST',body:JSON.stringify({user_id,password})}));}catch(e){setError(e.message)}finally{setBusy(false)}}
 return <div className="login-page">
  <div className="login-form">
   <Wordmark/>
   <div className="login-card">
    <div className="eyebrow">NOVACOMMERCE / DEMO</div>
    <h1>Sign in to Reconcile.</h1>
    <p>Choose a role for this session.</p>
    <button className="role-choice" disabled={busy} onClick={()=>login('USER-01')}>
     <span className="role-icon"><FileCheck2 size={21}/></span><span><strong>Reviewer</strong><small>Investigate cases and add evidence</small></span><ArrowUpRight size={18}/>
    </button>
    <button className="role-choice" disabled={busy} onClick={()=>login('USER-02')}>
     <span className="role-icon"><ShieldCheck size={21}/></span><span><strong>Approver</strong><small>Run checks and approve matches</small></span><ArrowUpRight size={18}/>
    </button>
    <details className="password-option"><summary>Workspace password</summary><input aria-label="Workspace password" type="password" value={password} onChange={e=>setPassword(e.target.value)}/></details>
    {error&&<div className="error" role="alert">{error}</div>}
   </div>
   <span className="login-footer">NOVACOMMERCE FINANCE <span>USD / SAMPLE DATA</span></span>
  </div>
  <div className="login-art" aria-hidden="true">
   <span className="art-label">SAMPLE WORKSPACE</span>
   <div className="receipt">
    <div className="receipt-head"><span>EXCEPTION DETAILS</span><Badge status="open"/></div>
    <div className="receipt-title">Payout PO-00435</div>
    <div className="receipt-line"><span>Expected deposit</span><strong>$435.00</strong></div>
    <div className="receipt-line"><span>Bank deposit</span><strong>$415.00</strong></div>
    <div className="receipt-stamp">Difference <strong>−$20.00</strong></div>
   </div>
   <span className="art-bottom">NOVACOMMERCE</span>
  </div>
 </div>
}

function workspaceRoute(){
 const route=location.hash.slice(1)||'overview';
 const page=route.split('?')[0];
 if(page==='exceptions')return 'overview';
 if(page==='sources')return 'overview?panel=imports';
 return route;
}

function App(){
 const [user,setUser]=useState(null),[authReady,setAuthReady]=useState(false),[view,setView]=useState(workspaceRoute),[summary,setSummary]=useState(null),[revision,setRevision]=useState(0),[error,setError]=useState(''),[toast,setToast]=useState(''),[running,setRunning]=useState(false);
 useEffect(()=>{api('/me').then(setUser).catch(()=>{}).finally(()=>setAuthReady(true));const change=()=>{const route=workspaceRoute();if(location.hash&&location.hash!=='#'+route)history.replaceState(null,'','#'+route);setView(route)};change();window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change)},[]);
 useEffect(()=>{if(user)api('/reconciliations/summary').then(setSummary).catch(e=>setError(e.message))},[user,revision]);
 useEffect(()=>{if(toast){let t=setTimeout(()=>setToast(''),4500);return()=>clearTimeout(t)}},[toast]);
 function navigate(page){location.hash=page;setView(page)}
 function refresh(message){setRevision(n=>n+1);if(message)setToast(message)}
 async function run(){setRunning(true);setError('');try{const r=await api('/runs',{method:'POST',body:JSON.stringify({as_of_date:summary?.run?.as_of_date||'2026-11-05'})});refresh(`Reconciliation complete · ${number(Object.values(r.summary).reduce((a,b)=>a+b,0))} checks`)}catch(e){setError(e.message)}finally{setRunning(false)}}
 async function logout(){try{await api('/logout',{method:'POST'});setUser(null);setSummary(null)}catch(e){setError(e.message)}}
 if(!authReady)return <Loading/>;
 if(!user)return <LoginScreen onLogin={setUser}/>;
 const nav=[
  ['overview','Overview',Activity],['checks','Matches',GitBranch],
  ['runs','Run history',Clock3],['guide','Reference',BookOpen]
 ];
 const [viewName,viewQuery]=view.split('?');
 const isDesk=viewName==='overview';
 const params=new URLSearchParams(viewQuery);
 const showImports=isDesk&&params.get('panel')==='imports';
 const pageTitle={overview:'Overview',checks:'Reconciliation',runs:'Run history',guide:'Reference'}[viewName]||'Reference';
 return <div className="operations-app">
  <aside className="navigation-rail">
   <a href="#overview" aria-label="Reconcile overview"><Wordmark/></a>
   <div className="rail-workspace"><span className="workspace-initial">N</span><div><strong>NovaCommerce</strong><small>Finance workspace</small></div></div>
   <nav className="section-nav" aria-label="Workspace">
    {nav.map(([key,title,Icon])=><button key={key} aria-label={title} title={title} aria-current={viewName===key?'page':undefined} onClick={()=>navigate(key)}>
     <Icon size={17}/><span>{title}</span>
    </button>)}
   </nav>
  </aside>
  <div className="workspace-body">
  <header className="masthead">
   <div className="breadcrumb">Finance operations <ChevronRight size={13}/> <strong>{pageTitle}</strong></div>
   <span className="session-role">{publicDemo?<small>Public demo · read-only</small>:<><small>Demo</small> {human(user.role)}</>}</span>
   {!publicDemo&&<button className="icon-button" aria-label="Sign out" title="Sign out" onClick={logout}><LogOut size={17}/></button>}
  </header>
  <main className="workspace-main">
   <div className="workspace-heading">
    <div><h1>{isDesk?'Reconciliation overview':pageTitle}</h1>{isDesk&&<p>Match results and exceptions for NovaCommerce.</p>}</div>
    <div className="page-actions">
     {summary?.run?.as_of_date&&<span className="date-pill"><Clock3 size={14}/> As of {shortDate(summary.run.as_of_date)}</span>}
     {isDesk&&<button className="secondary" onClick={()=>navigate('overview?panel=imports')}><Upload size={15}/> Imports</button>}
     {isDesk&&user.role==='approver'&&<button className="primary" disabled={running} onClick={run}>
      {running?<LoaderCircle size={16} className="spin"/>:<Play size={14}/>} {running?'Reconciling…':'Run reconciliation'}
     </button>}
    </div>
   </div>
   {error&&<div className="error" role="alert">{error}<button className="icon-button" aria-label="Dismiss error" onClick={()=>setError('')}><X size={16}/></button></div>}
   {!summary?<Loading/>:<>
    {isDesk&&<DeskStatus data={summary} navigate={navigate}/>}
    {isDesk?<CaseWorkspace user={user} users={summary.users||[]} revision={revision} refresh={refresh}/>
     :viewName==='checks'?<Checks key={view} revision={revision} initialStage={params.get('stage')||''}/>
     :viewName==='runs'?<Runs revision={revision}/>:<Guide/>}
   </>}
   <footer><span>NOVACOMMERCE / SAMPLE DATA</span><span>USD</span></footer>
  </main>
  </div>
  {showImports&&<ImportsDialog user={user} refresh={refresh} revision={revision} close={()=>navigate('overview')}/>}
  {toast&&<div className="toast" role="status"><CheckCircle2 size={18}/>{toast}</div>}
 </div>
}

function Wordmark(){
 return <span className="brand"><span className="brand-mark"><i/><i/><i/></span>Reconcile<span className="brand-dot">.</span></span>
}

function shortDate(value){
 return new Date(value+'T00:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'})
}

function SettlementChart({trend}){
 const [range,setRange]=useState('all');
 const [activeDate,setActiveDate]=useState(null);
 const days=range==='14'?trend.slice(-14):trend;
 const max=Math.max(...days.map(day=>day.expected_cents),1);
 const total=days.reduce((sum,day)=>sum+day.expected_cents,0);
 const active=days.find(day=>day.settlement_date===activeDate);
 const ticks=days.length>1?[days[0],days[Math.floor(days.length/2)],days.at(-1)]:days;
 return <section className="settlement-chart">
  <header><div className="eyebrow">PROCESSOR PAYOUTS</div><div className="range-control" aria-label="Settlement date range">
   <button aria-pressed={range==='all'} onClick={()=>{setRange('all');setActiveDate(null)}}>All dates</button>
   <button aria-pressed={range==='14'} onClick={()=>{setRange('14');setActiveDate(null)}}>Last 14 days</button>
  </div></header>
  <div className="chart-total">{money(active?.expected_cents??total)}</div>
  <div className="chart-caption">{active?shortDate(active.settlement_date):'Reported payout total'}<span>USD</span></div>
  {days.length?<><div className="chart-bars" aria-label="Reported payouts by settlement date" onMouseLeave={()=>setActiveDate(null)}>
   {days.map(day=><button key={day.settlement_date} className={'bar '+(activeDate===day.settlement_date?'highlight':'')}
    aria-label={shortDate(day.settlement_date)+', '+money(day.expected_cents)}
    style={{height:Math.max(day.expected_cents/max*100,2)+'%'}}
    onFocus={()=>setActiveDate(day.settlement_date)} onBlur={()=>setActiveDate(null)}
    onMouseEnter={()=>setActiveDate(day.settlement_date)} onClick={()=>setActiveDate(day.settlement_date)}/>)}
  </div><div className="chart-labels">{ticks.map((day,i)=><span key={i}>{shortDate(day.settlement_date)}</span>)}</div></>:<p className="chart-empty">No processor payouts yet.</p>}
 </section>
}

function DeskStatus({data,navigate}){
 const total=Object.values(data.counts).reduce((sum,count)=>sum+count,0);
 const matched=data.counts.reconciled||0;
 const rate=total?matched/total*100:0;
 return <>
  <div className="desk-visuals">
   <section className="match-overview" aria-label="Latest reconciliation">
    <h2>Match results</h2>
    <div className="match-overview-body">
     <div className="match-ring" style={{'--match-angle':rate+'%'}}>
      <div><strong>{total?rate.toFixed(1)+'%':'—'}</strong><span>Reconciled</span></div>
     </div>
     <div className="match-totals">
      <div><strong>{number(matched)}</strong><span>of {number(total)} checks reconciled</span></div>
      <button onClick={()=>document.getElementById('case-queue')?.focus()}>
       {number(data.open_cases)} open cases <ArrowUpRight size={14}/>
      </button>
     </div>
    </div>
    <dl className="summary-details">
     <div><dt>Flagged variance</dt><dd>{money(data.flagged_variance_cents)}</dd></div>
     <div><dt>Pending settlements</dt><dd>{number(data.counts.pending)}</dd></div>
    </dl>
   </section>
   <SettlementChart trend={data.trend}/>
  </div>
  <details className="stage-breakdown">
   <summary>Match results by stage</summary>
   <div className="match-index" aria-label="Matches by stage">
    {Object.entries(STAGES).map(([key,label])=>{
     const results=data.stages.filter(row=>row.stage===key);
     const matched=results.find(row=>row.status==='reconciled')?.count||0;
     const total=results.reduce((sum,row)=>sum+row.count,0);
     return <button key={key} onClick={()=>navigate('checks?stage='+key)}>
      <span className="match-label">{label}<ArrowUpRight size={13}/></span>
      <strong>{number(matched)}<small> / {number(total)}</small></strong>
      <span className="match-meter" aria-hidden="true"><i style={{width:(total?matched/total*100:0)+'%'}}/></span>
     </button>
    })}
   </div>
  </details>
 </>
}

function orderProfile(orderId){
 if(!/^ORD-\d{6}$/.test(orderId))return null;
 const entry=demoContext.orders[Number(orderId.slice(4))-1];
 if(!entry)return null;
 const [customerNumber,channelIndex]=entry;
 const customerId='CUST-'+String(customerNumber).padStart(5,'0');
 return {customerId,customer:demoContext.customers[customerId],channel:demoContext.channels[channelIndex]};
}

function CaseContext({evidence}){
 const order=evidence.orders?.[0];
 const profile=order&&orderProfile(order.order_id);
 const customer=profile?.customerId===order?.customer_id?profile?.customer:null;
 const bank=evidence.bank_transactions?.find(row=>row.account_id===demoContext.bank_account.id);
 const payout=evidence.processor_payouts?.[0];
 const account=demoContext.bank_account;
 if(!customer&&!bank&&!payout)return null;
 return <div className="case-context">
  {customer&&<><strong>{customer.name}</strong><span>{customer.market} · {profile.channel}</span></>}
  {!customer&&bank&&<><strong>{account.institution}</strong><span>{account.name}{bank.reference?' · '+bank.reference:''}</span></>}
  {!customer&&!bank&&payout&&<><strong>{demoContext.processor}</strong><span>Merchant settlement · {payout.payout_id}</span></>}
 </div>
}

function CaseWorkspace({user,users,revision,refresh}){
 const [result,setResult]=useState(null);
 const [status,setStatus]=useState('active');
 const [stage,setStage]=useState('');
 const [search,setSearch]=useState('');
 const [page,setPage]=useState(0);
 const [selected,setSelected]=useState(null);
 const [error,setError]=useState('');
 const pageSize=6;

 useEffect(()=>{
  let current=true;
  const query=new URLSearchParams({status,stage,search,offset:page*pageSize,limit:pageSize});
  const timer=setTimeout(()=>{
   api('/exceptions?'+query).then(data=>{
    if(!current)return;
    if(data.total>0&&!data.items.length&&page>0){
     setPage(Math.ceil(data.total/pageSize)-1);
     return;
    }
    setResult(data);
    setError('');
   }).catch(error=>{if(current)setError(error.message)});
  },search?180:0);
  return()=>{current=false;clearTimeout(timer)};
 },[status,stage,search,page,revision]);

 const active=result?.items.find(item=>item.id===selected)||result?.items[0];
 function updateFilter(setter,value){
  setter(value);
  setPage(0);
  setSelected(null);
  setResult(null);
 }
 function openCase(id){
  setSelected(id);
  if(window.matchMedia('(max-width: 620px)').matches){
   document.getElementById('case-sheet')?.scrollIntoView({block:'start'});
  }
 }
 return <section className="case-spread" aria-label="Case workspace">
  <div className="case-index">
   <div className="index-title">
    <h2 id="case-queue" tabIndex={-1}>Case queue</h2>
    {result&&<span>{number(result.total)}</span>}
    <a className="icon-button case-export" href={exceptionExport} download="reconciliation-exceptions.csv" aria-label="Export cases as CSV" title="Export cases as CSV"><Download size={15}/></a>
   </div>
   <div className="index-controls">
    <label className="index-search"><Search size={16}/><input aria-label="Search cases" value={search} placeholder="Search cases" onChange={e=>updateFilter(setSearch,e.target.value)}/></label>
    <div className="index-filters">
     <select aria-label="Case status" value={status} onChange={e=>updateFilter(setStatus,e.target.value)}>
      <option value="active">Active cases</option><option value="in_review">In review</option><option value="awaiting_evidence">Awaiting evidence</option><option value="resolved">Resolved</option><option value="">All cases</option>
     </select>
     <select aria-label="Case stage" value={stage} onChange={e=>updateFilter(setStage,e.target.value)}>
      <option value="">All stages</option>{Object.entries(STAGES).map(([key,name])=><option key={key} value={key}>{name}</option>)}
     </select>
    </div>
   </div>
   {error?<div className="error" role="alert">{error}</div>:!result?<Loading/>:result.items.length?<div className="index-entries">
    {result.items.map(item=><button key={item.id} className="index-entry" aria-pressed={item.id===active?.id} onClick={()=>openCase(item.id)}>
     <span className="index-entry-top"><strong>{item.entity_id}</strong><span>{money(item.variance_cents)}</span></span>
     <span className="index-finding">{orderProfile(item.entity_id)?.customer?.name||human(item.type)}</span>
     <span className="index-entry-meta"><Badge status={item.status}/><span>{STAGES[item.stage]}</span></span>
    </button>)}
   </div>:<Empty title="No cases found" text=""/>}
   {result&&<Pagination page={page} total={result.total} size={pageSize} onChange={value=>{setSelected(null);setResult(null);setPage(value)}}/>}
  </div>
  <div className="case-sheet" id="case-sheet">
   {active?<CasePanel key={active.id} id={active.id} user={user} users={users} changed={refresh} revision={revision}/>
    :<div className="sheet-empty"><FileCheck2 size={24}/><p>{result?'No case selected':'Loading cases…'}</p></div>}
  </div>
 </section>
}

function Checks({revision,initialStage}){
 const [result,setResult]=useState(null),[stage,setStage]=useState(initialStage),[status,setStatus]=useState(''),[search,setSearch]=useState(''),[page,setPage]=useState(0),[error,setError]=useState('');
 useEffect(()=>{let active=true;const t=setTimeout(()=>api(`/checks?${new URLSearchParams({stage,status,search,offset:page*50})}`).then(r=>{if(active)setResult(r)}).catch(e=>{if(active)setError(e.message)}),150);return()=>{active=false;clearTimeout(t)}},[stage,status,search,page,revision]);
 return <section className="card"><div className="card-heading"><div><h2>Reconciliation results</h2><p>Latest completed run</p></div><span className="subtle-chip">Rule set v1.0.0</span></div><div className="toolbar"><div className="search"><Search size={16}/><input placeholder="Search source record…" aria-label="Search checks" value={search} onChange={e=>{setSearch(e.target.value);setPage(0)}}/></div><select value={stage} aria-label="Check stage" onChange={e=>{setStage(e.target.value);setPage(0)}}><option value="">All stages</option>{Object.entries(STAGES).map(([k,v])=><option value={k} key={k}>{v}</option>)}</select><select value={status} aria-label="Check status" onChange={e=>{setStatus(e.target.value);setPage(0)}}><option value="">All statuses</option>{['reconciled','exception','review','pending','partial','not_eligible'].map(s=><option key={s} value={s}>{STATUS[s]}</option>)}</select></div>{error?<div className="error">{error}</div>:!result?<Loading/>:<><div className="table-scroll"><table><thead><tr><th>Source record</th><th>Stage</th><th>Expected</th><th>Observed</th><th>Variance</th><th>Result</th></tr></thead><tbody>{result.items.map(x=><tr key={x.id}><td><strong className="mono">{x.entity_id}</strong><small>{human(x.reason)}</small></td><td>{STAGES[x.stage]}</td><td className="amount">{money(x.expected_cents)}</td><td className="amount">{money(x.actual_cents)}</td><td className={'amount '+(x.variance_cents?'difference':'muted')}>{money(x.variance_cents)}</td><td><Badge status={x.status}/></td></tr>)}</tbody></table></div>{!result.total&&<Empty/>}<Pagination page={page} total={result.total} size={50} onChange={setPage}/></>}</section>
}

function ImportsDialog({user,refresh,revision,close}){
 const dialog=useRef(null);
 const [table,setTable]=useState('orders');
 const [records,setRecords]=useState(null);
 const [imports,setImports]=useState(null);
 const [page,setPage]=useState(0);
 const [browse,setBrowse]=useState(false);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const [feedback,setFeedback]=useState(null);
 const [rejections,setRejections]=useState(null);
 const tables=['orders','processor_transactions','processor_payouts','payout_items','bank_transactions','ledger_journals','ledger_entries','customers','bank_accounts','chart_of_accounts','ingestion_batches'];

 useEffect(()=>{dialog.current.showModal()},[]);
 useEffect(()=>{
  let active=true;
  api('/imports').then(data=>{if(active)setImports(data)}).catch(error=>{if(active)setError(error.message)});
  return()=>{active=false};
 },[revision]);
 useEffect(()=>{
  if(!browse)return;
  let active=true;
  api(`/sources/${table}?offset=${page*25}`).then(data=>{if(active)setRecords(data)})
   .catch(error=>{if(active)setError(error.message)});
  return()=>{active=false};
 },[browse,table,page,revision]);

 async function upload(event){
  const file=event.target.files[0];
  if(!file)return;
  setBusy(true);
  setError('');
  setFeedback(null);
  setRejections(null);
  try{
   const body=new FormData();
   body.append('file',file);
   const result=await api(`/imports/${table}`,{method:'POST',body});
   setFeedback(result);
   refresh('Import finished. Run reconciliation to refresh results.');
  }catch(error){setError(error.message)}
  finally{setBusy(false);event.target.value=''}
 }

 async function inspect(id){
  setError('');
  try{setRejections(await api(`/imports/${id}/rejections`))}
  catch(error){setError(error.message)}
 }

 return <dialog className="imports-dialog" ref={dialog} aria-labelledby="imports-title" onClose={close}>
  <div className="card-heading"><h2 id="imports-title">Imports</h2>
   <button className="icon-button" aria-label="Close imports" onClick={()=>dialog.current.close()}><X size={20}/></button>
  </div>
  <div className="toolbar">
   <select aria-label="Select source dataset" value={table} disabled={busy} onChange={e=>{setTable(e.target.value);setPage(0);setRecords(null)}}>
    {tables.map(name=><option key={name} value={name}>{human(name)}</option>)}
   </select>
   {user.role==='approver'&&<label className="secondary upload">
    <Upload size={15}/>{busy?'Importing…':'Import CSV'}<input type="file" aria-label="Import CSV" accept=".csv,text/csv" disabled={busy} onChange={upload}/>
   </label>}
   <button className="text-button" aria-expanded={browse} onClick={()=>setBrowse(value=>!value)}>{browse?'Hide records':'Browse records'}</button>
  </div>
  {error&&<div className="error" role="alert">{error}</div>}
  {feedback&&<div className="import-feedback" role="status">
   <CheckCircle2 size={17}/>{feedback.inserted} imported · {feedback.duplicates} duplicates skipped · {feedback.rejected} rejected
   {feedback.rejected>0&&<button className="text-button" onClick={()=>inspect(feedback.id)}>Inspect rejected rows</button>}
   <span>Run reconciliation to refresh results.</span>
  </div>}
  {browse&&<section aria-label="Source records">
   {records?<><DataTable rows={records.items} columns={records.columns}/>
    <Pagination page={page} total={records.total} size={25} onChange={value=>{setRecords(null);setPage(value)}}/></>:<Loading/>}
  </section>}
  {rejections&&<section className="import-rejections" aria-label="Rejected rows">
   <div className="card-heading"><h2>Rejected rows</h2><button className="text-button" onClick={()=>setRejections(null)}>Hide</button></div>
   {rejections.length?rejections.map(row=><div className="rejection" key={row.id}><strong>Row {row.row_number}</strong><p>{row.reason}</p><code>{row.payload}</code></div>):<Empty title="No rejected rows" text=""/>}
  </section>}
  <section aria-label="Import history">
   <div className="card-heading"><h2>Import history</h2></div>
   {imports===null?<Loading/>:!imports.length?<Empty title="No imports yet" text=""/>:<div className="table-scroll"><table>
    <thead><tr><th>File</th><th>Imported</th><th>Skipped</th><th>Rejected</th><th>Received</th></tr></thead>
    <tbody>{imports.slice(0,15).map(item=><tr key={item.id}>
     <td><strong>{item.filename}</strong><small>{human(item.table_name)}</small></td>
     <td>{number(item.inserted)}</td><td>{number(item.duplicates)}</td>
     <td>{item.rejected?<button className="text-button difference" onClick={()=>inspect(item.id)}>{item.rejected} · inspect</button>:'0'}</td>
     <td>{datetime(item.created_at)}</td>
    </tr>)}</tbody>
   </table></div>}
  </section>
 </dialog>
}
function DataTable({rows,columns,formatMoney=false}){if(!rows.length)return <Empty title="No source records"/>;const cols=columns||Object.keys(rows[0]);return <div className="table-scroll source-table"><table><thead><tr>{cols.map(c=><th key={c}>{human(formatMoney?c.replace(/_cents$/,''):c)}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{cols.map(k=><td key={k} className={k.endsWith('_cents')?'amount':'mono'}>{r[k]==null?<span className="muted">—</span>:formatMoney&&k.endsWith('_cents')?money(r[k]):String(r[k])}</td>)}</tr>)}</tbody></table></div>}

function Runs({revision}){
 const [runs,setRuns]=useState(null),[error,setError]=useState(''),[selected,setSelected]=useState(null);
 useEffect(()=>{api('/runs').then(setRuns).catch(e=>setError(e.message))},[revision]);
 return <section className="card"><div className="card-heading"><div><h2>Processing history</h2><p>Results and source fingerprints by run</p></div><span className="subtle-chip">Daily batch</span></div>{error?<div className="error">{error}</div>:!runs?<Loading/>:!runs.length?<Empty/>:<div className="table-scroll"><table><thead><tr><th>Run</th><th>Cutoff</th><th>Checks</th><th>Completed</th><th>Status</th><th/></tr></thead><tbody>{runs.map(r=><React.Fragment key={r.id}><tr className="clickable" onClick={()=>setSelected(selected===r.id?null:r.id)}><td><strong className="mono">{r.id.slice(0,16)}</strong><small>Rules v{r.rule_version}</small></td><td>{r.as_of_date}</td><td>{number(Object.values(JSON.parse(r.summary||'{}')).reduce((a,b)=>a+b,0))}</td><td>{datetime(r.completed_at)}</td><td><Badge status={r.status==='completed'?'reconciled':r.status}/></td><td><ChevronDown size={16}/></td></tr>{selected===r.id&&<tr><td colSpan="6"><div className="run-detail"><strong>Input fingerprint</strong><code>{r.input_fingerprint}</code><strong>Results</strong><div className="result-chips">{Object.entries(JSON.parse(r.summary||'{}')).map(([s,n])=><span key={s}>{STATUS[s]||s}: <b>{number(n)}</b></span>)}</div>{r.error&&<p className="difference">{r.error}</p>}</div></td></tr>}</React.Fragment>)}</tbody></table></div>}</section>
}

function CasePanel({id,user,users,changed,revision}){
 const [detail,setDetail]=useState(null),[tab,setTab]=useState('evidence'),[note,setNote]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[targetStatus,setTargetStatus]=useState('in_review'),[owner,setOwner]=useState(''),[sourcePath,setSourcePath]=useState(''),[record,setRecord]=useState(''),[bank,setBank]=useState('');
 async function load(){const r=await api(`/exceptions/${id}`);setDetail(r);setOwner(r.case.assigned_to||'');setBank(r.check.candidates[0]||'');return r}
 useEffect(()=>{
  let current=true;
  api(`/exceptions/${id}`).then(data=>{
   if(!current)return;
   setDetail(data);
   setOwner(data.case.assigned_to||'');
   setBank(data.check.candidates[0]||'');
  }).catch(error=>{if(current)setError(error.message)});
  return()=>{current=false};
 },[id,revision]);
 async function action(kind,extra={}){if(!detail)return;setBusy(true);setError('');try{await api(kind==='approve'?`/matches/${id}/approve`:`/exceptions/${id}/${kind}`,{method:'POST',body:JSON.stringify({note:note.trim()||(['assign'].includes(kind)?'Case ownership updated':' '),version:detail.case.version,...extra})});setNote('');await load();changed('Case updated.')}catch(e){setError(e.message);if(e.message.includes('Refresh'))await load().catch(()=>{})}finally{setBusy(false)}}
 const [fileOptions,setFileOptions]=useState([]); useEffect(()=>{api('/evidence-files').then(setFileOptions).catch(e=>setError(e.message))},[]);
 return <section className="case-panel" aria-label="Selected case"><div className="panel-top"><span><FileCheck2 size={15}/> EXCEPTION DETAILS</span>{detail&&<span>{detail.case.owner||'Unassigned'}</span>}</div>{!detail?<>{error?<div className="error">{error}</div>:<Loading/>}</>:<><div className="panel-title"><div className="eyebrow">{detail.case.id}</div><h2>{detail.case.entity_id}</h2><p>{human(detail.case.type)}</p><CaseContext evidence={detail.evidence}/><div><Badge status={detail.case.status}/><span>{STAGES[detail.case.stage]}</span></div></div><div className="case-amounts"><div><span>Expected</span><strong>{money(detail.check.expected_cents)}</strong></div><div><span>Observed</span><strong>{money(detail.check.actual_cents)}</strong></div><div><span>Difference</span><strong className="difference">{money(detail.check.variance_cents)}</strong></div></div>{!detail.case.finding_active&&<div className="import-feedback"><CheckCircle2 size={17}/>Source difference cleared. Reviewer closure required.</div>}{detail.case.finding_active&&detail.case.status==='resolved'&&<div className="import-feedback">Source finding retained. Resolution records the reviewer’s decision.</div>}<div className="panel-tabs">{[['evidence','Evidence'],['activity','Activity'],['resolve','Review']].filter(([key])=>!publicDemo||key!=='resolve').map(([k,v])=><button key={k} className={tab===k?'selected':''} onClick={()=>setTab(k)}>{v}</button>)}</div><div className="panel-content">{error&&<div className="error" role="alert">{error}</div>}{tab==='evidence'?<>{Object.entries(detail.evidence).map(([table,rows])=><details className="evidence-block evidence-disclosure" key={table}><summary>{human(table)} <span>{number(rows.length)}</span></summary>{rows.length?<DataTable rows={rows} columns={Object.keys(rows[0]).filter(k=>!['source_system','batch_id','source_created_at'].includes(k))} formatMoney/>:<p className="muted">No linked source records found.</p>}</details>)}{!publicDemo&&<button className="secondary" onClick={()=>setTab('resolve')}>Review this difference <ArrowRight size={16}/></button>}</>:tab==='activity'?<><h3>Investigation history</h3><div className="timeline">{detail.history.map(h=><div className="timeline-item" key={h.id}><span className="timeline-dot"/><strong>{human(h.action)}</strong><small>{h.actor_name||h.actor} · {datetime(h.created_at)}</small><p>{h.note}</p></div>)}</div>{!publicDemo&&<><label className="field-label">Add a review note<textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="What did you investigate or confirm?" rows="4"/></label><button className="primary" disabled={busy||!note.trim()} onClick={()=>action('notes')}>Save note <Plus size={15}/></button></>}</>:<><div className="action-section"><h3>Case ownership</h3><label className="field-label">Assign to<select value={owner} onChange={e=>setOwner(e.target.value)}><option value="">Unassigned</option>{users.map(u=><option key={u.user_id} value={u.user_id}>{u.display_name}</option>)}</select></label><button className="secondary" disabled={busy} onClick={()=>action('assign',{assigned_to:owner||null})}>Update owner</button></div><div className="action-section"><h3>Supporting evidence</h3><p>Attach the original file and, optionally, the exact record.</p><label className="field-label">Source file<select value={sourcePath} onChange={e=>setSourcePath(e.target.value)}><option value="">Select an evidence file</option>{fileOptions.map(f=><option value={f.path} key={f.path}>{f.label}</option>)}</select></label><label className="field-label">Record identifier<input value={record} onChange={e=>setRecord(e.target.value)} placeholder="Optional source record ID"/></label><label className="field-label">Investigation note / decision reason<textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="Explain what the evidence demonstrates…" rows="3"/></label><button className="secondary" disabled={busy||!sourcePath||!note.trim()} onClick={()=>action('evidence',{source_path:sourcePath,source_record_id:record})}><Plus size={15}/>Attach evidence</button>{detail.attachments.map(a=><div className="attachment" key={a.id}><FileText size={16}/><div><strong>{a.source_path}</strong><small>{a.note}</small></div><Check size={15}/></div>)}</div><div className="action-section"><h3>Update case status</h3><p>Closing an active difference requires supporting evidence and the approver role.</p><select aria-label="New case status" value={targetStatus} onChange={e=>setTargetStatus(e.target.value)}>{['open','in_review','awaiting_evidence','resolved','dismissed'].map(s=><option key={s} value={s} disabled={['resolved','dismissed'].includes(s)&&user.role!=='approver'}>{STATUS[s]}</option>)}</select><button className="primary" disabled={busy||!note.trim()} onClick={()=>action('status',{status:targetStatus})}>Save status <Check size={16}/></button></div>{detail.case.stage==='payout_to_bank'&&detail.check.status==='review'&&<div className="action-section"><h3>Approve a proposed match</h3><p>An approver other than the case owner must confirm the candidate with supporting evidence.</p><select aria-label="Bank candidate" value={bank} onChange={e=>setBank(e.target.value)}>{detail.check.candidates.map(b=><option value={b} key={b}>{b}</option>)}</select><button className="primary" disabled={busy||user.role!=='approver'||!bank||!note.trim()} onClick={()=>action('approve',{bank_txn_id:bank})}><ShieldCheck size={16}/>Approve selected match</button></div>}</>}</div><div className="panel-footer"><ShieldCheck size={15}/>Audit history available in Activity</div></>}</section>
}

function Guide(){
 return <div className="guide-grid">
  <section className="card guide"><h2>Matching rules</h2>
   {Object.entries(STAGES).map(([key,name],i)=><div className="guide-entry" key={key}><h3>{name}</h3><p>{[
    'Captured payments must cover the order amount.',
    'Charges, fees, refunds, and other payout items must add up to the reported payout.',
    'A bank credit must have a compatible reference, account, currency, amount, and date.',
    'Bank activity must match cash entries in posted, balanced journals.'
   ][i]}</p></div>)}
  </section>
  <section className="card guide"><h2>Review permissions</h2>
   <div className="guide-entry"><h3>Reviewer</h3><p>Investigate cases, add evidence, and leave notes.</p></div>
   <div className="guide-entry"><h3>Approver</h3><p>Run reconciliation, import files, and close cases. Match approvals require an approver other than the case owner.</p></div>
   <div className="guide-entry"><h3>Flagged variance</h3><p>The sum of absolute differences across active cases. A source issue can appear in more than one check.</p></div>
  </section>
 </div>
}

createRoot(document.getElementById('root')).render(<App/>);
