import { useState } from 'react';
import { Empty, Status } from './components';
import type { Mutate } from './OfferDetail';
import type { Pickup, Workspace } from './types';
import { ClockBasis, DateCue } from './DispatchEvidence';
import { localCalendarDate } from './dispatch';
import { projection } from './workspaceModel';
import { routeLink } from './routes';
import { ActivityList } from './Dashboard';

export function PickupCard({ item, data, busy, mutate, today }: { item: Pickup; data: Workspace; busy: boolean; mutate: Mutate; today: string }) {
  const [role, setRole] = useState(data.roles[0]);
  const [when, setWhen] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const payload = { digest: item.plan_digest, run_id: item.run_id, org: item.org };
  const closed = ['invalidated', 'confirmed'].includes(item.state);
  return <article className="panel padded pickup-card"><div className="section-heading"><Status value={item.state}/><span>{item.quantity} {item.unit}</span></div><h2>{item.org}</h2><a href={`#/offers/${item.offer_id}`}>{item.title}</a>
    <DateCue offer={data.offers.find(row => row.offer.id === item.offer_id)?.offer} today={today} closed={closed}/>
    {item.role && <p>Collecting role: {item.role}</p>}{item.agreed_at && <p>Scheduled: <time dateTime={item.agreed_at}>{new Date(item.agreed_at).toLocaleString()}</time></p>}
    {item.state === 'invalidated' && <p className="notice">The allocation changed or the commitment expired. This agreement cannot authorize collection.</p>}
    {item.state === 'confirmed' && <p className="success-note">Collection confirmed in {data.mode === 'sandbox' ? 'this synthetic sandbox' : 'the coordinator register'}. This share cannot be claimed again. {typeof item.confirmed_at === 'number' && Number.isFinite(item.confirmed_at) && item.confirmed_at > 0 ? <time dateTime={new Date(item.confirmed_at * 1000).toISOString()}>{new Date(item.confirmed_at * 1000).toLocaleString()}</time> : 'Confirmation time unavailable.'}</p>}
    {!closed && !data.can_write && <p className="notice">{data.authorization_note}</p>}
    {!closed && data.can_write && (item.state === 'unclaimed' ? <form onSubmit={e => { e.preventDefault(); void mutate(item.offer_id, 'pickup', { ...payload, action: 'claim', role }); }}><label>Collecting role<select value={role} onChange={e => setRole(e.target.value)}>{data.roles.map(r => <option key={r}>{r}</option>)}</select></label><p className="small-note">Choose an organisational role. Do not enter a name or phone number.</p><button disabled={busy}>Claim this share</button></form> : <>
      <form onSubmit={e => { e.preventDefault(); void mutate(item.offer_id, 'pickup', { ...payload, action: 'schedule', agreed_at: new Date(when).toISOString() }); }}><label>Collection time (your local time)<input type="datetime-local" required value={when} onChange={e => setWhen(e.target.value)}/></label><button className="secondary" disabled={busy || !when}>Save collection time</button>{!when && <p className="small-note">Choose a future time within the next 14 days.</p>}</form>
      <form className="confirmation" onSubmit={e => { e.preventDefault(); void mutate(item.offer_id, 'pickup', { ...payload, action: 'confirm', consent: confirmed }); }}><label className="check-label"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/>This collection actually happened{data.mode === 'sandbox' ? ' in the simulation' : ''}.</label><button disabled={busy || !confirmed}>Confirm collection</button>{!confirmed && <p className="small-note">Confirm arrival before marking this share collected.</p>}</form>
    </>)}
  </article>;
}
export function Pickups({ data, busy, mutate }: { data: Workspace; busy: boolean; mutate: Mutate }) {
  const [filter, setFilter] = useState('open');
  const [today] = useState(localCalendarDate);
  const rows = projection(data).pickups.filter(p => filter === 'all' || (filter === 'open' ? !['confirmed', 'invalidated'].includes(p.state) : p.state === filter));
  return <><div className="page-heading"><div><p className="eyebrow">TURN A DECISION INTO A COLLECTION</p><h1>Pickups</h1><p>A published allocation is a plan. Only an explicit confirmation records collection.</p></div></div><ClockBasis today={today}/><div className="toolbar"><h2>Collection tasks</h2><label>Show <select value={filter} onChange={e => setFilter(e.target.value)}><option value="open">Needs attention</option><option value="all">All collections</option><option value="confirmed">Confirmed</option><option value="invalidated">Invalidated</option></select></label></div>{rows.length ? <div className="pickup-grid">{rows.map(p => <PickupCard key={`${p.offer_id}-${p.org}-${p.state}-${p.commitment_digest || p.plan_digest}`} item={p} data={data} busy={busy} mutate={mutate} today={today}/>)}</div> : <Empty title="No collection tasks here">{data.pickups.length ? 'Choose another filter to see recorded collections.' : <>Review an offer and approve its exact allocation to create collection tasks. <a href="#/offers">Open offers →</a></>}</Empty>}</>;
}
export function History({ data, selected = '' }: { data: Workspace; selected?: string }) {
  const records = projection(data).records;
  return <><div className="page-heading"><div><p className="eyebrow">A RECORD YOU CAN RETURN TO</p><h1>{data.mode === 'sandbox' ? 'Sandbox history' : 'Published history'}</h1><p>{data.mode === 'sandbox' ? 'Approvals in this synthetic session. No public records were written.' : 'Earlier records remain at their original addresses. A correction is a new record.'}</p></div><a className="button secondary" href={routeLink('/workspace', { offer: selected })}>Return to workspace →</a></div><section className="panel padded"><h2>Activity register</h2><p className="small-note">All available activity in this workspace. Scheduled collection dates are not event timestamps.</p><ActivityList data={data}/></section>{records.length ? <section className="panel padded"><h2>Allocation records</h2><div className="record-list">{records.map(r => <article key={r.key}><div><h2><a href={`#/offers/${r.offer_id}`}>{r.key}</a></h2><p>{r.superseded_by ? `Superseded by ${r.superseded_by}` : 'Current record in this history'}</p><p>{Number.isFinite(r.published_at) && r.published_at > 0 ? <time>{new Date(r.published_at * 1000).toLocaleString()}</time> : 'Publication time unavailable'}</p><p className="digest">{r.content_digest}</p></div><span className="badge">{r.mode === 'sandbox' ? 'Simulation' : 'Published'}</span></article>)}</div></section> : <Empty title="No records yet">Nothing has been approved in this workspace. Review an offer before recording an allocation.</Empty>}</>;
}
