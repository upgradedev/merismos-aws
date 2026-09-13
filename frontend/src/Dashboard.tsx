import { Empty, Status } from './components';
import { ClockBasis, DateCue } from './DispatchEvidence';
import { activity, amount, metrics, priorityOffers, projection, type Filter } from './workspaceModel';
import { routeLink } from './routes';
import type { Workspace } from './types';

export function ActivityList({ data, limit }: { data: Workspace; limit?: number }) {
  const events = activity(data).slice(0, limit);
  return events.length ? <ol className="activity-list">{events.map(event => <li key={event.id}><a href={routeLink('/workspace', { offer: event.offerId })}><strong>{event.title}</strong><span>{event.detail}</span><small>{event.at === null ? 'Event time unavailable' : <time dateTime={new Date(event.at * 1000).toISOString()}>{new Date(event.at * 1000).toLocaleString()}</time>}</small></a></li>)}</ol> : <p className="muted">No recorded activity in this scope yet. Run results appear with their selected offer; collection is recorded only after explicit confirmation.</p>;
}
export function Dashboard({ data, today, unit, selected, pickup }: { data: Workspace; today: string; unit: string; selected: string; pickup?: string }) {
  const units = [...new Set(projection(data).offers.map(row => row.offer.unit).filter(Boolean))].sort();
  const currentUnit = unit || units[0] || '';
  const values = metrics(data, currentUnit, today);
  const quantity = (n: number | null) => n === null ? 'Unknown' : `${amount(n)} ${currentUnit}`.trim();
  const cards: { label: string; value: string; note: string; filter: Filter }[] = [
    { label: 'Offered', value: quantity(values.offered), note: 'All offers in the selected unit', filter: 'all' },
    { label: 'Allocated in computed plans', value: quantity(values.allocated), note: `${values.unknown} offers with unknown allocation; includes drafts`, filter: 'allocated' },
    { label: 'Unallocated in computed plans', value: quantity(values.unallocated), note: `${values.unknown} offers excluded as unknown; not a safety clearance`, filter: 'unallocated' },
    { label: 'Pending pickups', value: String(values.pending), note: 'Unclaimed, claimed, scheduled or overdue shares', filter: 'pending' },
    { label: 'Confirmed collections', value: String(values.confirmed), note: 'Explicitly confirmed shares; never inferred from allocation', filter: 'confirmed' },
    { label: 'Dated urgency', value: String(values.urgent), note: 'Unrecorded offers dated tomorrow, today or earlier', filter: 'urgent' },
  ];
  const priority = priorityOffers(data, today).slice(0, 5);
  const observed = projection(data);
  const focus = observed.offers.find(row => row.offer.id === selected) || priority[0] || observed.offers[0];
  return <>
    <div className="page-heading"><div><p className="eyebrow">FOR VOLUNTEER FOOD COORDINATORS</p><h1>Dashboard</h1><p>Share a donation across five local organisations, explain the allocation and arrange each pickup.</p></div><div style={{ display: 'flex', gap: '10px' }}><a className="button secondary" href="#/offers/new">+ Add offer</a></div></div>
    <section className="panel padded coordinator-start" aria-label="Your next donation"><p className="eyebrow">ONE OFFER → A CONSIDERED SPLIT → A COLLECTION HANDOFF</p>
      <h2>{focus ? `Next offer: ${focus.offer.title}` : 'Have a donation to share?'}</h2>
      {focus ? <><p className="offer-lead"><strong>{focus.offer.quantity} {focus.offer.unit}</strong> from {focus.offer.donor} · Collect {focus.offer.collection_date || 'date not provided'}</p><p>{focus.offer.note || 'Match this donation to the network’s food needs, safety rules and collection capacity.'}</p><p>{focus.plan?.recorded ? 'The allocation is approved. Arrange the collection tasks and record receipt separately.' : focus.plan ? 'A proposed allocation is ready with recipient reasons. Review it before approving any pickup.' : 'Start by calculating a proposed allocation. You can review every recipient and reason before approving.'}</p><a className="button" href={routeLink('/workspace', {offer: focus.offer.id})}>{focus.plan?.recorded ? 'Arrange this offer’s pickups' : focus.plan ? 'Review this offer’s allocation' : 'Start with this offer'} →</a></> : <><p>Add a named offer with quantity and collection date, then review who can use it and why.</p><a className="button" href="#/offers/new">Start a donation →</a></>}
      <p className="small-note">Proposed and approved allocations are decisions. Scheduled pickups are arrangements. Received food requires explicit collection confirmation. This demo uses synthetic offers.</p>
    </section>
    <div className="scope-line"><span>{data.mode === 'sandbox' ? 'Isolated synthetic sandbox' : 'Live synthetic record view'} · {data.network} · All available records</span><label>Metric unit <select value={currentUnit} onChange={event => { location.hash = routeLink('/dashboard', { offer: selected, pickup, unit: event.target.value }).slice(1); }}>{units.length ? units.map(value => <option key={value}>{value}</option>) : <option value="">No unit available</option>}</select></label></div>
    <ClockBasis today={today}/>
    <details className="panel padded"><summary>Session outcomes and demo limitations</summary><section aria-label="Observed session outcomes"><h2>Observed session outcomes</h2><p>For volunteer coordinators sharing donated food across local organisations. <a href="#/offers/new">Try an editable donation →</a></p><p>Success: add an ambient offer, run, review and approve. Refusal: try chilled food with a broken cold chain. Correction: revise rejected intake information and submit again.</p><dl className="facts"><div><dt>Offers with decisions</dt><dd>{observed.offers.filter(row => !!row.result.outcome).length}</dd></div><div><dt>Refused offers</dt><dd>{observed.offers.filter(row => ['blocked', 'refused_by_gate'].includes(row.status)).length}</dd></div><div><dt>Recorded decisions</dt><dd>{observed.records.length}</dd></div><div><dt>Superseded records</dt><dd>{observed.records.filter(record => !!record.superseded_by).length}</dd></div></dl><p className="small-note">Current session snapshot only; reruns replace the displayed offer outcome. Human active time and benefits are unknown. Strands runs the sandbox agent loop with scripted responses; live model execution must be established from that run's evidence.</p></section></details>
    {values.conflicts > 0 && <p className="notice">{values.conflicts} conflicting identities were withheld. Totals cover unambiguous rows only. Refresh and inspect the source before acting.</p>}
    <section className="metric-grid" aria-label="Workspace metrics">{cards.map(card => <a className="metric-card" key={card.filter} href={routeLink('/records', { offer: selected, pickup, filter: card.filter, unit: currentUnit })}><span>{card.label}</span><strong>{card.value}</strong><small>{card.note}</small><span className="metric-drill">Inspect records ↗</span></a>)}</section>
    <div className="dashboard-grid"><section className="panel padded"><div className="section-heading"><h2>Priority work</h2><a href={routeLink('/workspace', { offer: selected, pickup })}>Open workspace →</a></div>{priority.length ? <div className="priority-list">{priority.map(row => <a key={row.offer.id} href={routeLink('/workspace', { offer: row.offer.id })}><div className="section-heading"><strong>{row.offer.title}</strong><Status value={row.status}/></div><span>{row.offer.quantity} {row.offer.unit} · {row.offer.donor}</span><DateCue offer={row.offer} today={today} closed={!!row.plan?.recorded}/></a>)}</div> : <Empty title="No priority offers">There are no unrecorded offers or pending pickups in the current scope.</Empty>}</section>
    <section className="panel padded"><div className="section-heading"><h2>Recent activity</h2><a href={routeLink('/history', { offer: selected, pickup })}>History →</a></div><ActivityList data={data} limit={5}/><p className="small-note">Available timestamps are shown as reported. Undated states are not treated as recent events.</p></section></div>
  </>;
}
