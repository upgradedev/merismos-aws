import { useState } from 'react';
import type { Mutate } from './OfferDetail';
import type { OfferRow, Result, Workspace } from './types';
import { allocationTotal, projection } from './workspaceModel';

export function decisionRows(before: Result, after: Result, ready: boolean) {
  const names = [...new Set([
    ...(before.draft_allocations || []).map(a => a.org), ...Object.keys(before.draft_barred_because || {}),
    ...(after.draft_allocations || []).map(a => a.org), ...Object.keys(after.draft_barred_because || {}),
  ])];
  const explain = (result: Result, org: string) => {
    const share = result.draft_allocations?.find(a => a.org === org);
    return share ? `${share.quantity}: ${share.reason}` : result.draft_barred_because?.[org] ? `0: ${result.draft_barred_because[org]}` : 'No decision reported';
  };
  return names.map(org => ({org, before: explain(before, org), after: ready ? explain(after, org) : 'Replan required; no current allocation'}));
}

export function pickupManifest(row: OfferRow, data: Workspace): string {
  const total = allocationTotal(row);
  const current = row.plan;
  const change = row.replan;
  return [
    'MERISMOS · PICKUP MANIFEST · SYNTHETIC DEMONSTRATION',
    `Scope: ${data.mode}. ${data.mode === 'sandbox' ? 'Isolated simulation. No public publication or real collection.' : 'Read-only view unless an authenticated coordinator is present.'}`,
    `Workspace revision: ${data.version}. This export is a snapshot, not a recipient receipt.`,
    `Offer: ${row.offer.id} · ${row.offer.title}`,
    `Donor organisation: ${row.offer.donor}`,
    `Offered: ${row.offer.quantity} ${row.offer.unit}; collect: ${row.offer.collection_date}; use by: ${row.offer.use_by || 'unknown'}`,
    `Allergens: ${row.offer.allergens?.join(', ') || 'unknown; confirm before collection'}`,
    `Donor note: ${row.offer.note || 'not provided'}`,
    `Run: ${row.result.run_id || 'not started'}; status: ${row.status}`,
    `Allocated: ${total === null ? 'unknown' : `${total} ${row.offer.unit}`}; no recipient: ${total === null ? 'unknown' : `${Number((row.offer.quantity - total).toFixed(6))} ${row.offer.unit}`}`,
    current?.recorded ? 'Allocation recorded by the server. Collection requires separate confirmation.' : 'DRAFT / REPLAN REQUIRED. No pickup is authorized by this document.',
    `Record address: ${current?.key || 'no current record'}; exact-plan digest: ${current?.digest || 'unavailable'}`,
    'ALLOCATION AND EXCLUSIONS',
    ...(row.result.draft_allocations || []).map(a => `${a.org}: ${a.quantity} ${row.offer.unit}. ${a.reason}`),
    ...Object.entries(row.result.draft_barred_because || {}).map(([org, reason]) => `${org}: no share. ${reason}`),
    `Policy ceiling: ${row.result.fairness_cap ? `${row.result.fairness_cap.share * 100}% from ${row.result.fairness_cap.source}` : 'unknown in this result'}. Network policy, not universal or certified fairness.`,
    ...(change ? ['DISRUPTION AND REPLAN', `${change.org}: simulated capacity reduced from allocated ${change.previous_quantity} to ${change.capacity} ${change.unit}. Source: ${change.source}.`,
      `Previous ${change.before_recorded ? 'recorded' : 'draft'} plan: ${change.before_key}; digest: ${change.before_digest}. Original evidence retained.`,
      ...decisionRows(change.before, row.result, total !== null).map(r => `${r.org}: before ${r.before}; after ${r.after}`)] : []),
    'COLLECTION COMMITMENTS',
    ...data.pickups.filter(p => p.offer_id === row.offer.id).map(p => `${p.org}: ${p.quantity} ${p.unit} · ${p.state} · ${p.role || 'role unassigned'} · ${p.agreed_at || 'time not agreed'} · commitment digest ${p.commitment_digest || p.plan_digest}`),
    'LIMITS',
    'Recheck the current workspace and exact plan before acting. Changed plans invalidate old commitments.',
    'A hash binds bytes, not food safety, arrival or independent recipient proof. Human/coordinator proof NOT_RUN.',
    'No message is sent. No model network call runs in the sandbox. Food rescued and time saved are not measured.',
  ].join('\n');
}

export function downloadManifest(text: string) {
  const url = URL.createObjectURL(new Blob([text], {type: 'text/plain;charset=utf-8'}));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = 'merismos-pickup-manifest.txt';
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function DispatchJourney({row, data}: {row: OfferRow; data: Workspace}) {
  const changed = !!row.replan;
  const replanned = changed && allocationTotal(row) !== null;
  const currentPickups = projection(data).pickups.filter(p => row.plan?.recorded && p.offer_id === row.offer.id && p.plan_digest === row.plan.digest && p.run_id === row.plan.run_id && p.state !== 'invalidated');
  const received = currentPickups.filter(p => p.state === 'confirmed').length;
  const scheduled = currentPickups.filter(p => p.state === 'scheduled').length;
  return <section className="panel padded journey" aria-label="Offer to pickup journey"><div className="section-heading"><h2>From offer to pickup</h2><button className="secondary" onClick={() => document.getElementById('next-decision')?.focus()}>Go to next decision ↓</button></div>
    <p>{row.offer.quantity} {row.offer.unit} · Collect {row.offer.collection_date || 'date not provided'} · {row.offer.title}</p>
    <ol className="decision-stages" aria-label="Allocation and collection status">
      <li>Proposed<strong>{changed ? (replanned ? (row.plan?.recorded ? 'Approved in sandbox' : row.plan ? 'Fresh approval required' : 'No feasible allocation') : 'Capacity correction needs a new plan') : row.plan ? 'Allocation computed' : 'Needs review'}</strong></li>
      <li>Approved<strong>{row.plan?.recorded ? 'Exact allocation recorded' : 'Not approved'}</strong></li>
      <li>Scheduled<strong>{scheduled ? `${scheduled} of ${currentPickups.length} pickups scheduled` : 'No time agreed yet'}</strong></li>
      <li>Collected<strong>{received ? `${received} of ${currentPickups.length} shares confirmed${data.mode === 'sandbox' ? ' in simulation' : ''}` : 'No receipt confirmed'}</strong></li>
    </ol></section>;
}

export function ReplanComparison({row}: {row: OfferRow}) {
  const change = row.replan;
  if (!change) return null;
  const ready = allocationTotal(row) !== null;
  const rows = decisionRows(change.before, row.result, ready);
  return <section className="panel padded" aria-label="Before and after disruption"><h2>What changed and why</h2>
    <p>{change.org}: simulated collection capacity reduced from an allocation of {change.previous_quantity} to {change.capacity} {change.unit}. Applies to this offer; evidence: {change.source}.</p>
    <p className="notice">{row.plan?.recorded ? 'The new exact plan is approved in the sandbox. Old commitments remain invalid; arrange collection against the new plan.' : row.plan ? 'Replanned against the new constraint. Fresh exact-plan approval is required before new pickup commitments.' : ready ? 'Replan completed with no feasible allocation. No pickup is authorized; review the exclusions below.' : 'Old allocation is no longer actionable. Recalculate the split to apply the new capacity limit.'} Original {change.before_recorded ? 'recorded' : 'draft'} plan and its evidence are retained.</p>
    <div className="comparison-rows">{rows.map(r => <article key={r.org}><h3>{r.org}</h3><p>Before ({change.unit}): {r.before}</p><p>After ({change.unit}): {r.after}</p></article>)}</div>
    <details><summary>Previous exact plan identity</summary><p>{change.before_key}</p><p className="break-all">{change.before_digest}</p><p>Prior run: {change.before.run_id}. This identity is historical and cannot approve the current plan.</p></details>
    <details><summary>Previous record text · historical</summary><pre>{change.before.draft_body || 'Previous record text unavailable.'}</pre></details>
  </section>;
}

export function DisruptionControl({row, data, busy, mutate}: {row: OfferRow; data: Workspace; busy: boolean; mutate: Mutate}) {
  const shares = row.result.draft_allocations || [];
  const [org, setOrg] = useState(shares[0]?.org || '');
  const [capacity, setCapacity] = useState('0');
  const share = shares.find(a => a.org === org);
  const confirmed = data.pickups.some(p => p.offer_id === row.offer.id && p.state === 'confirmed');
  const allowed = data.mode === 'sandbox' && data.can_write && !!row.plan && !confirmed && allocationTotal(row) !== null;
  const valid = /^\d+(?:\.\d{1,2})?$/.test(capacity) && Number.isFinite(Number(capacity)) && Number(capacity) >= 0 && !!share && Number(capacity) < share.quantity;
  return <details className="panel padded disruption"><summary>Rehearse a collection disruption</summary><p>Record a lower collection capacity for one allocated organisation, then recalculate the split. The original plan stays in history; existing pickup commitments become invalid. This is sandbox evidence, not a report from a recipient.</p>
    {allowed ? <form onSubmit={e => { e.preventDefault(); if (!busy && valid && row.plan) void mutate(row.offer.id, 'disrupt', {org, capacity: Number(capacity), consent: true, digest: row.plan.digest, run_id: row.plan.run_id}); }}>
      <label>Organisation affected<select value={org} disabled={busy} onChange={e => { setOrg(e.target.value); setCapacity('0'); }}>{shares.map(a => <option key={a.org}>{a.org}</option>)}</select></label>
      <label>New collection capacity ({row.offer.unit})<input type="number" min="0" max={share ? share.quantity - 0.01 : 0} step="0.01" value={capacity} disabled={busy} onChange={e => setCapacity(e.target.value)}/></label>
      <p>Zero means this organisation cannot collect any of this offer. Other safety, premises, policy and capacity constraints still apply.</p><button disabled={busy || !valid}>Record simulated disruption</button>{!valid && <p className="small-note">Enter a capacity below the selected allocation, zero or above, with at most two decimals.</p>}
    </form> : <p className="notice">{data.mode !== 'sandbox' ? 'Switch to Sandbox to rehearse; live source records cannot be edited here.' : confirmed ? 'Collection is already confirmed. This donation cannot be reallocated.' : 'A consistent computed plan is required before recording a disruption.'}</p>}
  </details>;
}

export function ManifestExport({row, data}: {row: OfferRow; data: Workspace}) {
  const [message, setMessage] = useState('');
  const text = pickupManifest(row, data);
  async function copy() {
    try { await navigator.clipboard.writeText(text); setMessage('Manifest copied. No message was sent.'); }
    catch { setMessage('Clipboard unavailable. Select and copy the manifest below.'); }
  }
  return <details className="panel padded"><summary>Pickup manifest · copy or download</summary><p>Plain text for the coordinator's existing handoff. Drafts and simulated commitments stay labelled. No spreadsheet formulas or links are executed.</p>
    <textarea aria-label="Pickup manifest" rows={12} readOnly value={text}/><div className="form-actions"><button type="button" className="secondary" onClick={() => void copy()}>Copy pickup manifest</button><button type="button" className="secondary" onClick={() => { try { downloadManifest(text); setMessage('Manifest downloaded as plain text.'); } catch { setMessage('Download unavailable. Select and copy the manifest below.'); } }}>Download pickup manifest</button></div><p role="status">{message}</p>
  </details>;
}
