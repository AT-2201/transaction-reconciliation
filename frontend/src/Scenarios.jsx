import React, {useEffect, useState} from 'react';

const usd = cents => cents == null ? 'Missing' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD'
}).format(cents / 100);

const label = value => value.replaceAll('_', ' ');

export function Trace({trace}) {
  const {composition, settlement, components, credits} = trace;
  return <div className="trace-grid">
    <section><h3>Payment activity</h3>
      {components.length ? components.map(row => <div className="trace-line" key={row.type}>
        <span>{label(row.type)} ({row.count})</span><strong>{usd(row.amount)}</strong>
      </div>) : <p>No linked payment activity.</p>}
      <div className="trace-line"><span>Net of items</span><strong>{usd(composition.actual_cents)}</strong></div>
    </section>
    <section><h3>Processor payout</h3><strong>{usd(composition.expected_cents)}</strong>
      <p>{trace.payout_id} · {label(composition.status)}</p></section>
    <section><h3>Bank deposit</h3><strong>{usd(settlement.actual_cents)}</strong>
      <p>{label(settlement.status)} · {label(settlement.reason)}</p>
      {credits.map(({record}) => <p key={record.bank_txn_id}>{record.bank_txn_id} · {usd(record.amount_cents)} total credit</p>)}
    </section>
    <section><h3>Ledger</h3>{credits.length ? credits.map(({record, ledger}) => <p key={record.bank_txn_id}>
      {ledger ? `${usd(ledger.actual_cents)} posted · ${label(ledger.status)}` : 'No ledger check for this credit'}
    </p>) : <p>Waiting for a bank record.</p>}</section>
  </div>;
}

export function PayoutTrace({payoutId, api, revision}) {
  const [trace, setTrace] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let current = true;
    api('/traces/' + encodeURIComponent(payoutId)).then(data => {
      if (current) setTrace(data);
    }).catch(err => { if (current) setError(err.message); });
    return () => { current = false; };
  }, [payoutId, api, revision]);
  if (error) return <p role="alert">{error}</p>;
  return trace ? <Trace trace={trace}/> : <p>Loading trace…</p>;
}

export function Scenarios({api}) {
  const [data, setData] = useState(null);
  const [evaluation, setEvaluation] = useState(null);
  const [error, setError] = useState('');
  const [phase, setPhase] = useState('missing');
  const [duplicate, setDuplicate] = useState(false);
  useEffect(() => {
    let current = true;
    Promise.all([api('/scenarios'), api('/evaluation')]).then(([scenarios, scores]) => {
      if (current) { setData(scenarios); setEvaluation(scores); }
    }).catch(err => { if (current) setError(err.message); });
    return () => { current = false; };
  }, [api]);
  if (error) return <p role="alert">{error}</p>;
  if (!data) return <p>Loading scenarios…</p>;
  const trace = phase === 'rerun' ? data.after : data.before;
  return <div className="scenario-stack">
    <p>Explore saved results from the reconciliation engine. Your choices apply to this page.</p>
    <section className="card scenario-card">
      <h2>Missing bank deposit</h2>
      <p>The processor paid {usd(data.before.settlement.expected_cents)}. The deposit arrived in a later bank statement export.</p>
      <Trace trace={trace}/>
      <div className="scenario-actions">
        <button className="secondary" disabled={phase !== 'missing'} onClick={() => setPhase('added')}>Add sample bank deposit</button>
        <button className="primary" disabled={phase !== 'added'} onClick={() => setPhase('rerun')}>Show reconciliation result</button>
        <button className="text-button" onClick={() => setPhase('missing')}>Reset</button>
      </div>
      <div role="status">
        {phase === 'added' && <p>Sample deposit added. The displayed checks still show the original run.</p>}
        {phase === 'rerun' && <><p>Source difference cleared. Case status: {label(data.case.case.status)}.</p>
          <details><summary>Case history</summary><ul>{data.case.history.map(event => <li key={event.id}>{event.note}</li>)}</ul></details></>}
      </div>
    </section>
    <section className="card scenario-card">
      <h2>Two payouts, one deposit</h2>
      <p>A shared settlement reference connects two payouts of $600 and $400 to a $1,000 bank deposit.</p>
      <div className="scenario-actions">
        <button className="secondary" aria-pressed={!duplicate} onClick={() => setDuplicate(false)}>One deposit</button>
        <button className="secondary" aria-pressed={duplicate} onClick={() => setDuplicate(true)}>Duplicate deposit</button>
      </div>
      <p role="status">{duplicate ? 'Two matching bank credits require review.' : 'Both payouts reconcile. The engine allocates $600 and $400 to the same credit.'}</p>
      {(duplicate ? data.ambiguous : data.grouped).map(item => <details key={item.payout_id}>
        <summary>{item.payout_id} · {usd(item.settlement.expected_cents)} · {label(item.settlement.status)}</summary>
        <Trace trace={item}/>
      </details>)}
    </section>
    <section className="card scenario-card">
      <h2>Matching evaluation</h2>
      <p>Coverage is automatic matches divided by all labeled checks. False matches include wrong statuses or incorrect labeled allocations. The holdout contains later synthetic records.</p>
      <div className="table-scroll"><table>
        <thead><tr><th>Split</th><th>Checks</th><th>Automatic coverage</th><th>False matches</th><th>Allocations checked</th><th>Review findings</th></tr></thead>
        <tbody>{Object.entries(evaluation.metrics).map(([split, row]) => <tr key={split}>
          <td>{split}</td><td>{row.checks.toLocaleString()}</td><td>{(100 * row.auto_matches / row.checks).toFixed(1)}%</td>
          <td>{row.false_matches} of {row.auto_matches.toLocaleString()}</td><td>{row.link_checks.toLocaleString()}</td><td>{row.review_findings}</td>
        </tr>)}</tbody>
      </table></div>
    </section>
  </div>;
}
