import { useState } from 'react';
import type { OfferRow, Workspace } from './types';
import { DateCue } from './DispatchEvidence';
import { localCalendarDate } from './dispatch';
import { isPending, projection } from './workspaceModel';

export const labels: Record<string, string> = {
  needs_replan: 'Replan required',
  not_started: 'Needs review', awaiting_approval: 'Awaiting approval', running: 'Working out the split',
  blocked: 'Safety refusal', refused_by_gate: 'Gate refused', nothing_to_allocate: 'No allocation',
  failed: 'Run failed', recorded: 'Sandbox record', published: 'Published', unclaimed: 'Needs a collector',
  claimed: 'Claimed', scheduled: 'Scheduled', confirmed: 'Confirmed collected', overdue: 'Overdue', invalidated: 'Invalidated',
};
export function Status({ value }: { value: string }) {
  return <span className={`badge badge-${value}`}>{labels[value] || value}</span>;
}
export function Empty({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="empty"><div aria-hidden="true" className="empty-symbol">↳</div><h2>{title}</h2><p>{children}</p></div>;
}
export function describedBy(...ids: (string | false | undefined)[]) {
  return ids.filter(Boolean).join(' ') || undefined;
}
export function Offers({ data: snapshot }: { data: Workspace }) {
  const data = { ...snapshot, ...projection(snapshot) };
  const [query, setQuery] = useState('');
  const [today] = useState(localCalendarDate);
  const [filter, setFilter] = useState('all');
  const rows = data.offers.filter(row => `${row.offer.title} ${row.offer.id} ${row.offer.donor}`.toLowerCase().includes(query.toLowerCase()) && (filter === 'all' || row.status === filter));
  return <>
    <div className="page-heading"><div><p className="eyebrow">THE NETWORK'S INBOX</p><h1>Offers</h1><p>Every donation needs a considered split. Start with an offer.</p></div><a className="button" href="#/offers/new">+ Add offer</a></div>
    <div className="summary-grid"><div className="summary-card"><span>Awaiting a decision</span><strong>{data.offers.filter(o => ['not_started', 'awaiting_approval'].includes(o.status)).length}</strong><small>Offers to review together</small></div><div className="summary-card"><span>Collections needing attention</span><strong>{data.pickups.filter(isPending).length}</strong><a href="#/pickups">Open collection tasks →</a></div><div className="summary-card"><span>Recorded allocations</span><strong>{data.records.length}</strong><small>{data.mode === 'sandbox' ? 'Synthetic sandbox records only' : 'A record does not confirm collection'}</small></div></div>
    <section className="panel"><div className="toolbar"><h2>Donation offers</h2><div className="filters"><label><span className="sr-only">Search offers</span><input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search offers or donors"/></label><label><span className="sr-only">Filter status</span><select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All statuses</option>{['not_started', 'awaiting_approval', 'blocked', 'recorded', 'published'].map(s => <option key={s} value={s}>{labels[s]}</option>)}</select></label></div></div>
      {rows.length ? <div className="table-scroll"><table><caption className="sr-only">Current donation offers and next steps</caption><thead><tr><th scope="col">Offer / donor</th><th scope="col">Available</th><th scope="col">Dates / calendar cue</th><th scope="col">Status</th><th scope="col">Next step</th></tr></thead><tbody>{rows.map(({ offer, status }) => <tr key={offer.id}><td><a className="offer-link" href={`#/offers/${offer.id}`}>{offer.title}</a><small>{offer.id} · {offer.donor}</small></td><td className="nowrap">{offer.quantity} {offer.unit}</td><td><DateCue offer={offer} today={today}/></td><td><Status value={status}/></td><td><a href={`#/offers/${offer.id}`} aria-label={`Review ${offer.title}`}>Review →</a></td></tr>)}</tbody></table></div> : <Empty title="No offers match">Clear your search or choose another status. <button type="button" className="text-button" onClick={() => { setQuery(''); setFilter('all'); }}>Clear search and status</button></Empty>}
    </section><p className="footnote">Synthetic organisations and donations. Quantities describe the fixture, never measured food rescued.</p>
  </>;
}
export function Summary({ row }: { row: OfferRow }) {
  const [copied, setCopied] = useState('');
  async function copy() {
    try { await navigator.clipboard.writeText(row.summary); setCopied('Copied. You choose where to share it.'); }
    catch { setCopied('Clipboard unavailable. Select and copy the text below.'); }
  }
  return <section className="panel padded"><div className="section-heading"><h2>Reasons to share</h2><button className="secondary" onClick={copy}>Copy summary</button></div><p>Ready for your coordinator group chat. No message is sent by Merismos.</p><textarea aria-label="Shareable reasons summary" readOnly rows={8} value={row.summary}/><p role="status">{copied}</p></section>;
}
