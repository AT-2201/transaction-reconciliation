import React, {useEffect, useState} from 'react';
import {TransactionTrail, RecordList, amount, readable} from './TransactionTrail';

const usd = cents => cents == null ? 'Missing' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD'
}).format(cents / 100);

const label = value => value.replaceAll('_', ' ');

export function Trace({trace}) {
  const {composition, settlement, components, credits} = trace;
  const uncertain = settlement.status === 'review';
  const ledgerChecks = credits.filter(credit => credit.ledger);
  const ledgerStatus = !credits.length || !ledgerChecks.length ? 'unavailable'
    : ledgerChecks.length !== credits.length ? 'unavailable'
    : ledgerChecks.some(credit => credit.ledger.status !== 'reconciled') ? 'exception' : 'reconciled';
  const ledgerTotal = ledgerChecks.length === credits.length && credits.length
    ? ledgerChecks.reduce((sum, credit) => sum + credit.ledger.actual_cents, 0) : null;
  const nodes = [
    {id:'payments', title:'Payment activity', value:amount(composition.actual_cents), status:'source',
      caption:'Signed payout items',
      content:<RecordList rows={components.map(row => [readable(row.type) + ' (' + row.count + ')', amount(row.amount)])}/>},
    {id:'payout', title:'Processor payout', value:amount(composition.expected_cents), status:composition.status,
      caption:trace.payout_id,
      content:<RecordList rows={[
        ['Payout', trace.payout_id], ['Reported net', amount(composition.expected_cents)],
        ['Signed item total', amount(composition.actual_cents)], ['Difference', amount(composition.variance_cents)],
        ['Matching rule', readable(composition.reason)]
      ]}/>},
    {id:'bank', title:'Bank deposit',
      value:uncertain ? credits.length + ' candidate' + (credits.length === 1 ? '' : 's') : amount(settlement.actual_cents),
      status:settlement.status, caption:readable(settlement.reason),
      content:<><RecordList rows={credits.flatMap(({record}) => [
        ['Bank record', record.bank_txn_id], ['Full credit', amount(record.amount_cents)],
        ['Account', record.account_id], ['Currency', record.currency], ['Value date', record.value_date],
        ['Reference', record.reference || 'Missing reference']
      ])}/>{!uncertain && credits.length > 0 && <p className="trail-note">
        Amount allocated to this payout {amount(settlement.actual_cents)}.
        {settlement.reason === 'grouped_bank_credit' && ' The full bank credit also covers other payouts.'}
      </p>}</>},
    {id:'ledger', title:'Ledger', value:uncertain ? 'Candidate records' : amount(ledgerTotal),
      status:uncertain ? 'review' : ledgerStatus,
      caption:credits.length > 1 ? 'Cash postings for all candidate credits' : 'Cash postings for full bank credit',
      content:<><RecordList rows={credits.flatMap(({record, ledger}) => [
        ['Bank record', record.bank_txn_id], ['Checked cash postings', ledger ? amount(ledger.actual_cents) : 'No ledger check'],
        ['Result', ledger ? readable(ledger.reason) : 'Unavailable']
      ])}/>{uncertain && <p className="trail-note">These postings belong to candidate deposits. The bank match still requires review.</p>}</>}
  ];
  return <TransactionTrail nodes={nodes}/>;

}

export function PayoutTrace({payoutId, api, revision}) {
  const [trace, setTrace] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let current = true;
    setTrace(null);
    setError('');
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
