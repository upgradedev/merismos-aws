import { useEffect, useState } from 'react';
import { Empty, Status, Summary } from './components';
import { DonationEvidence, AllocationEvidence, DecisionPanel, type Mutate } from './OfferDetail';
import { PickupCard } from './Pickups';
import { DateCue, EvidenceBundle } from './DispatchEvidence';
import { filters, filterOffers, projection, type Filter } from './workspaceModel';
import { routeLink } from './routes';
import type { OfferRow, Workspace } from './types';
import { DispatchJourney, DisruptionControl, ManifestExport, ReplanComparison } from './DispatchJourney';

type PickupSelection = { pickup?: string; onPickupChange?: (pickup: string) => void };
function DispatchTasks({ data, row, busy, mutate, today, pickup, onPickupChange }: { data: Workspace; row: OfferRow; busy: boolean; mutate: Mutate; today: string } & PickupSelection) {
  const pickups = projection(data).pickups.filter(p => p.offer_id === row.offer.id);
  const identity = (p: typeof pickups[number]) => JSON.stringify([p.org, p.commitment_digest || p.plan_digest]);
  const first = pickups[0] ? identity(pickups[0]) : '';
  const [localSelected, setLocalSelected] = useState(first);
  const selected = pickup ?? localSelected;
  const setSelected = onPickupChange ?? setLocalSelected;
  // New tasks arrive after approval. Capture the initial identity once; the API
  // orders unclaimed rows first, so array position changes after every claim.
  useEffect(() => { if (!selected && first) setSelected(first); }, [selected, first, setSelected]);
  const item = pickups.find(p => identity(p) === selected);
  return <section className="dispatch-tasks" aria-label="Selected offer pickups"><div className="section-heading"><h2>Claim & collection</h2><a href={routeLink('/pickups', { offer: row.offer.id })}>All pickup tasks →</a></div>
    <p className="small-note">Approval records the allocation. A claim, an agreed time and explicit arrival confirmation are separate steps.</p>
    {pickups.length > 0 && <><label htmlFor="pickup-organisation">Pickup organisation</label><select id="pickup-organisation" value={item ? identity(item) : ''} onChange={event => setSelected(event.target.value)}>{!item && <option value="">Choose a current pickup</option>}{pickups.map(p => <option key={identity(p)} value={identity(p)}>{p.org} · {p.quantity} {p.unit} · {p.state}</option>)}</select></>}
    {item ? <PickupCard key={`${identity(item)}-${item.state}-${data.version}`} item={item} data={data} busy={busy} mutate={mutate} today={today}/> : <p className="notice">{selected ? 'The selected pickup is unavailable. Choose a current pickup before acting.' : 'No pickup is authorised for this offer. Approve the exact allocation before claiming a share.'}</p>}
  </section>;
}
export function DispatchWorkspace({ data, selected, filter, unit, today, busy, mutate, pickup, onPickupChange }: { data: Workspace; selected: string; filter: Filter; unit: string; today: string; busy: boolean; mutate: Mutate } & PickupSelection) {
  const [query, setQuery] = useState('');
  const source = projection(data);
  const row = source.offers.find(item => item.offer.id === selected);
  const rows = filterOffers(data, filter, unit, today, query);
  const hiddenSelection = row && !rows.includes(row) && !rows.some(item => item.offer.id === row.offer.id);
  return <>
    <div className="page-heading"><div><p className="eyebrow">DISPATCH WORKSPACE</p><h1>{row?.offer.title || 'Dispatch workspace'}</h1><p>{row ? `${row.offer.id} · ${row.offer.donor}` : 'Select an offer to review its evidence and next decision.'}</p></div><a className="button secondary" href="#/offers/new">+ Add offer</a></div>
    <div className="workspace-context"><a href="#/offers" className="back-link">← All offers</a><span>{source.offers.length} offers · {row ? '1 offer in focus' : 'No offer in focus'}</span><a href={routeLink('/records', { offer: selected, pickup })}>Inspect records →</a></div>
    {row && <DispatchJourney row={row} data={data}/>}
    {source.conflicts > 0 && <p className="notice">Conflicting source identities were withheld. Refresh and review before acting.</p>}
    <div className="dispatch-grid"><section className="panel intake-stream" aria-label="Intake and allocation"><div className="pane-heading"><span className="eyebrow">01</span><h2>Intake & allocation</h2><span className="badge">{filters[filter]}{unit ? ` · ${unit}` : ''}</span></div><div className="stream-search"><label>Search offers<input type="search" placeholder="Offer, donor or identifier" value={query} onChange={e => setQuery(e.target.value)}/></label></div>
      {hiddenSelection && <p className="notice">The selected offer is outside this filter. <a href={routeLink('/workspace', { offer: selected, pickup })}>Clear filters and keep the selection</a>.</p>}
      {rows.map(item => <div className={`offer-entry${selected === item.offer.id ? ' selected' : ''}`} key={item.offer.id}><a className="offer-select" href={routeLink('/workspace', { offer: item.offer.id, filter, unit })} aria-current={selected === item.offer.id ? 'true' : undefined}><div className="section-heading"><strong>{item.offer.title}</strong><span>{item.offer.quantity} {item.offer.unit}</span></div><span>{item.offer.donor}</span><div className="offer-meta"><Status value={item.status}/><DateCue offer={item.offer} today={today} closed={!!item.plan?.recorded}/></div></a>
        {selected === item.offer.id && <div className="selected-evidence"><DonationEvidence row={item}/><AllocationEvidence row={item}/><ReplanComparison row={item}/>{!!item.result.run_id && <details><summary>Share allocation reasons</summary><Summary key={`${item.result.run_id}-${item.status}`} row={item}/></details>}</div>}</div>)}
      {!rows.length && <Empty title="No offers match">Clear your search or <a href={routeLink('/workspace', { offer: selected, pickup })}>clear filters</a>.</Empty>}
    </section><aside id="next-decision" tabIndex={-1} className="decision-pane" aria-label="Decision and dispatch"><div className="pane-heading"><span className="eyebrow">02</span><h2>Decision & dispatch</h2></div>{row ? <><p className="decision-context">{row.offer.id} · {row.offer.title}</p>{hiddenSelection ? <p className="notice">Show this offer's evidence before acting. <a href={routeLink('/workspace', { offer: selected, pickup })}>Review selected offer</a>.</p> : <><DecisionPanel key={`${data.mode}-${selected}-${row.result.run_id}-${row.plan?.digest}-${row.plan?.evidence_digest}-${data.version}`} row={row} data={data} busy={busy} mutate={mutate}/>
      <DisruptionControl key={`${data.mode}-${selected}-${row.plan?.digest}-${row.status}`} row={row} data={data} busy={busy} mutate={mutate}/><DispatchTasks key={`${data.mode}-${selected}-${row.plan?.digest}`} data={data} row={row} today={today} busy={busy} mutate={mutate} pickup={pickup} onPickupChange={onPickupChange}/><ManifestExport key={`manifest-${data.mode}-${selected}-${data.version}`} row={row} data={data}/><EvidenceBundle key={`evidence-${data.mode}-${selected}-${data.version}`} row={row} data={data}/></>}</> : <Empty title={selected ? 'Offer not found' : 'No offers yet'}>{selected ? <>This offer is missing or has conflicting data. Select a current offer from the stream. <a href="#/offers">Choose a current offer</a></> : <>Add an offer to start a considered allocation. <a href="#/offers/new">Add an offer</a></>}</Empty>}</aside></div>
  </>;
}
