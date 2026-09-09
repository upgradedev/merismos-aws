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
  return <>
    <div className="page-heading"><div><p className="eyebrow">COMMUNITY COORDINATION</p><h1>Dashboard</h1><p>Review the split. Keep the reasons. Close the collection.</p></div><a className="button" href="#/offers/new">+ Add offer</a></div>
    <div className="scope-line"><span>{data.mode === 'sandbox' ? 'Isolated synthetic sandbox' : 'Live synthetic record view'} · {data.network} · All available records</span><label>Metric unit <select value={currentUnit} onChange={event => { location.hash = routeLink('/dashboard', { offer: selected, pickup, unit: event.target.value }).slice(1); }}>{units.length ? units.map(value => <option key={value}>{value}</option>) : <option value="">No unit available</option>}</select></label></div>
    <ClockBasis today={today}/>
    {values.conflicts > 0 && <p className="notice">{values.conflicts} conflicting identities were withheld. Totals cover unambiguous rows only. Refresh and inspect the source before acting.</p>}
    <section className="metric-grid" aria-label="Workspace metrics">{cards.map(card => <a className="metric-card" key={card.filter} href={routeLink('/records', { offer: selected, pickup, filter: card.filter, unit: currentUnit })}><span>{card.label}</span><strong>{card.value}</strong><small>{card.note}</small><span className="metric-drill">Inspect records ↗</span></a>)}</section>
    <div className="dashboard-grid"><section className="panel padded"><div className="section-heading"><h2>Priority work</h2><a href={routeLink('/workspace', { offer: selected, pickup })}>Open workspace →</a></div>{priority.length ? <div className="priority-list">{priority.map(row => <a key={row.offer.id} href={routeLink('/workspace', { offer: row.offer.id })}><div className="section-heading"><strong>{row.offer.title}</strong><Status value={row.status}/></div><span>{row.offer.quantity} {row.offer.unit} · {row.offer.donor}</span><DateCue offer={row.offer} today={today} closed={!!row.plan?.recorded}/></a>)}</div> : <Empty title="No priority offers">There are no unrecorded offers or pending pickups in the current scope.</Empty>}</section>
    <section className="panel padded"><div className="section-heading"><h2>Recent activity</h2><a href={routeLink('/history', { offer: selected, pickup })}>History →</a></div><ActivityList data={data} limit={5}/><p className="small-note">Available timestamps are shown as reported. Undated states are not treated as recent events.</p></section></div>
  </>;
}
