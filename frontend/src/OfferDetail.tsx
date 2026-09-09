import { useState } from 'react';
import { Empty, Status, Summary } from './components';
import type { OfferRow, Workspace } from './types';
import { DigestCustody } from './DispatchEvidence';
import { AllocationBars } from './AllocationBars';

export type Mutate = (offer: string, kind: string, payload?: Record<string, unknown>) => Promise<boolean>;
export function OfferDetail({ row, data, busy, mutate }: { row?: OfferRow; data: Workspace; busy: boolean; mutate: Mutate }) {
  const [consent, setConsent] = useState(false);
  if (!row) return <Empty title="Offer not found">This link does not name an offer in this workspace. <a href="#/offers">Return to offers</a>.</Empty>;
  const { offer, result, plan } = row;
  const allocated = (result.draft_allocations || []).reduce((total, item) => total + item.quantity, 0);
  return <>
    <a href="#/offers" className="back-link">← All offers</a>
    <div className="page-heading"><div><p className="eyebrow">{offer.id} · {offer.category}</p><h1>{offer.title}</h1><p>{offer.donor}</p></div><Status value={row.status}/></div>
    <div className="detail-grid"><section className="panel padded"><h2>The donation</h2><dl className="facts"><div><dt>Offered</dt><dd>{offer.quantity} {offer.unit}</dd></div><div><dt>Collection date</dt><dd>{offer.collection_date}</dd></div><div><dt>Use by</dt><dd>{offer.use_by || 'Not provided'}</dd></div><div><dt>Allergens</dt><dd>{offer.allergens === null ? 'Unknown; needs checking' : offer.allergens.length ? offer.allergens.join(', ') : 'Declared none'}</dd></div></dl><p className="donor-note">{offer.note}</p></section>
    <section className="panel padded action-card"><p className="eyebrow">NEXT DECISION</p><h2>{row.status === 'running' ? 'The fleet is working' : plan?.recorded ? 'Arrange the collections' : 'Review the allocation'}</h2><p>{result.note || 'Ask the fleet to read the offer and the network’s safety, capacity, equity and premises rules.'}</p>
      {row.status === 'running' && <p role="status">{row.progress?.stage || 'Starting the runner'} · {row.progress?.specialists_answered || 0} specialists answered</p>}
      {plan?.recorded ? <a href="#/pickups" className="button">Open collection tasks →</a> : <button disabled={busy || !data.can_write || row.status === 'running'} onClick={() => mutate(offer.id, 'run')}>{busy ? 'Working…' : result.run_id ? 'Re-run the fleet' : 'Work out the split'}</button>}
      {!data.can_write && <p className="notice">{data.authorization_note} Switch to Sandbox to try the full flow.</p>}
      {row.status === 'running' && <p className="small-note">This run is still in progress. Its result appears here when the backend finishes.</p>}
      {result.run_id && <p className="footnote break-all">Run {result.run_id}. {data.provider}.</p>}
    </section></div>
    {result.outcome && <section className="panel padded"><div className="section-heading"><h2>Allocation & reasons</h2><Status value={row.status}/></div>
      {!!result.draft_allocations?.length && <><div className="allocation-total"><span>Allocated <strong>{allocated} {offer.unit}</strong></span><span>No recipient <strong>{Number((offer.quantity - allocated).toFixed(6))} {offer.unit}</strong></span></div><p className="allocation-scale">Both bars use the full {offer.quantity} {offer.unit} offer as their scale, not recipient transport or storage capacity.{plan && result.fairness_cap && <> Policy source: {result.fairness_cap.source}.</>}</p><div className="allocation-list">{result.draft_allocations.map(a => <article key={a.org}><div className="recipient-heading"><h3>{a.org}</h3><strong>{a.quantity} {offer.unit}</strong></div><p>{a.reason}</p><AllocationBars allocation={a} offer={offer} cap={plan ? result.fairness_cap : null}/></article>)}</div></>}
      {!!Object.keys(result.draft_barred_because || {}).length && <div className="exclusions"><h3>Not receiving a share</h3>{Object.entries(result.draft_barred_because || {}).map(([org, reason]) => <div key={org}><strong>{org}</strong><p>{reason}</p></div>)}</div>}
      {!result.draft_allocations?.length && <p className="notice">{result.note || 'No allocation was approved by the deterministic gate.'}</p>}
      <details><summary>Specialist findings and deterministic checks</summary>{result.envelopes?.map(e => <article key={e.specialist} className="finding"><h3>{e.specialist} · {e.status}</h3><p>{e.reason}</p>{e.findings.map((f, i) => <p key={i}>{f.severity}: {f.detail}</p>)}</article>)}</details>
    </section>}
    {plan && <section className="panel padded approval-card"><p className="eyebrow">ONE DECISION · EXACT BYTES</p><h2>{plan.recorded ? 'The recorded plan' : 'Approve this exact plan'}</h2><p>{data.mode === 'sandbox' ? 'Sandbox approval records your decision only inside this synthetic session. It does not publish to the public record bucket.' : 'This approval authorizes a permanent public allocation record at the address below. Collection must still be confirmed separately.'}</p><dl><dt>Record address</dt><dd className="break-all">{plan.key}</dd></dl><DigestCustody key={`${data.mode}-${plan.digest}-${plan.recorded}`} plan={plan} mode={data.mode}/><details><summary>Read the exact record text</summary><pre>{plan.body}</pre></details>
      {!plan.recorded && <form onSubmit={async e => { e.preventDefault(); const saved = await mutate(offer.id, 'approve', { consent, digest: plan.digest, run_id: plan.run_id, key: plan.key }); if (saved) setConsent(false); }}><label className="check-label"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>I have reviewed this exact allocation and record address, and approve this plan.</label><button disabled={!consent || busy || !data.can_write}>{busy ? 'Recording decision…' : data.mode === 'sandbox' ? 'Approve in sandbox' : 'Approve and publish'}</button>{!consent && <p className="small-note">Review the record and tick the confirmation before approving.</p>}{!data.can_write && <p className="small-note">{data.authorization_note}</p>}</form>}
    </section>}
    {!!result.run_id && <Summary key={`${result.run_id}-${row.status}`} row={row}/>}
  </>;
}
