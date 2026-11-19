import React, {useId, useState} from 'react';
import {ArrowRight, Check, ChevronDown, CircleAlert, Clock3} from 'lucide-react';

export const amount = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD'
}).format(value / 100);

export const readable = value => (value || '').replaceAll('_', ' ');

const statusLabel = {
  reconciled: 'Matched', exception: 'Difference', review: 'Needs review',
  pending: 'Pending', partial: 'Partial', source: 'Source record', unavailable: 'Unavailable'
};

export function TransactionTrail({nodes}) {
  const [selected, setSelected] = useState(null);
  const panelId = useId();
  const active = nodes.find(node => node.id === selected);
  return <section className="transaction-trail" aria-label="Transaction trail">
    <div className="trail-heading"><h3>Transaction trail</h3><span>Select a record to inspect it</span></div>
    <ol className="trail-nodes">
      {nodes.map(node => {
        const Icon = node.status === 'reconciled' ? Check : node.status === 'pending' ? Clock3 : CircleAlert;
        return <li key={node.id} className={'trail-node ' + node.status}>
          <button type="button" aria-expanded={selected === node.id} aria-controls={panelId}
            onClick={() => setSelected(selected === node.id ? null : node.id)}>
            <span className="trail-node-title">{node.title}<ChevronDown size={13}/></span>
            <strong>{node.value}</strong>
            <span className="trail-state">{node.status === 'source' ? null : <Icon size={13}/>}
              {statusLabel[node.status] || readable(node.status)}</span>
            <small>{node.caption}</small>
          </button>
          <ArrowRight className="trail-connector" size={17} aria-hidden="true"/>
        </li>;
      })}
    </ol>
    <div id={panelId} hidden={!active} className="trail-records">
      {active&&<><h4>{active.title}</h4>{active.content}</>}
    </div>
  </section>;
}

export function RecordList({rows}) {
  return rows.length ? <dl className="trail-facts">{rows.map(([name, value], index) =>
    <div key={index}><dt>{name}</dt><dd>{value == null ? 'Unavailable' : String(value)}</dd></div>
  )}</dl> : <p>No linked records were found in this run.</p>;
}
