import { useId, useState } from 'react';
import { calendarDay, dateCue } from './dispatch';
import type { Mode, Offer, OfferRow, Plan, Workspace } from './types';

export function evidenceBundle(row: OfferRow, data: Workspace): string {
  const records = data.records.filter(record => record.offer_id === row.offer.id);
  const pickups = data.pickups.filter(pickup => pickup.offer_id === row.offer.id);
  return [
    'MERISMOS · COORDINATOR EVIDENCE BUNDLE',
    `Scope: ${data.mode} · synthetic donations and organisations`,
    `Workspace revision: ${data.version}; application release: not supplied in this snapshot`,
    `Provider: ${data.provider}`,
    'Provider configuration does not prove a model call or an independent critic ran.',
    `Offer: ${row.offer.id} · ${row.offer.title}`,
    `Run: ${row.result.run_id || 'not started'}; observed outcome: ${row.status}`,
    `Progress: ${row.progress?.stage || 'no active progress reported'}`,
    `Decision: ${row.result.note || 'No decision reported.'}`,
    `Source: offers/${row.offer.id}.json (public offer projection)`,
    `Applied allocation policy: ${row.result.fairness_cap?.source || 'unknown in this result'}`,
    'Raw manifests, internal logs and personal identities are not included in this public export.',
    ...((row.result.envelopes || []).map(item => `${item.specialist}: ${item.status} · ${item.reason}`)),
    row.summary,
    `Record address: ${row.plan?.key || 'none'}; state: ${row.plan?.recorded ? 'server reported record' : 'not recorded'}`,
    `Approval digest: ${row.plan?.digest || 'unavailable'}`,
    `Evidence digest: ${row.plan?.evidence_digest || 'unavailable'}`,
    'Hashes bind bytes; they do not prove source truth, food safety, delivery or independent custody verification.',
    'RECORD HISTORY',
    ...(records.length ? records.map(record => `${record.key} · run ${record.run_id} · ${record.superseded_by ? `superseded by ${record.superseded_by}` : 'current in available history'}`) : ['No saved record in this snapshot.']),
    'COLLECTION HANDOFF',
    ...(pickups.length ? pickups.map(item => `${item.org}: ${item.quantity} ${item.unit} · ${item.state} · ${item.role || 'role unassigned'} · ${item.agreed_at || 'time not agreed'}`) : ['No collection commitment reported.']),
    'RECOVERY AND LIMITS',
    ...pickups.flatMap(item => (item.feedback || []).map(event => `Handoff report: ${item.org} · ${event.code} · ${event.role} · ${new Date(event.at * 1000).toISOString()}`)),
    'After a failed or uncertain request, refresh and inspect the same run and record before retrying. Do not infer failure from a timeout.',
    'A correction needs a new review and exact consent. Existing record addresses remain historical evidence.',
    'Human active time, time saved, food rescued and beneficiary impact: unknown; not measured.',
    'No message is sent by this export. A recorded allocation is not a confirmed collection.',
  ].join('\n');
}

export function EvidenceBundle({ row, data }: { row: OfferRow; data: Workspace }) {
  const [feedback, setFeedback] = useState('');
  const text = evidenceBundle(row, data);
  async function copy() {
    try { await navigator.clipboard.writeText(text); setFeedback('Evidence bundle copied. You choose where to share it.'); }
    catch { setFeedback('Clipboard unavailable. Select and copy the evidence text.'); }
  }
  return <details className="panel padded"><summary>Evidence bundle and recovery</summary><p>Readable evidence from this API snapshot. Review before sharing.</p><textarea aria-label="Evidence bundle" readOnly rows={14} value={text}/><button type="button" className="secondary" onClick={copy}>Copy evidence bundle</button><p role="status">{feedback}</p></details>;
}

export function DateCue({ offer, today, closed = false }: { offer?: Offer; today: string; closed?: boolean }) {
  const cue = dateCue(offer, today, closed);
  const other = cue.kind === 'Collection' ? offer?.use_by : offer?.collection_date;
  return <span className={`date-cue date-cue-${cue.tone}`}>
    <span className="date-cue-label">{cue.label}</span>
    {cue.date ? <span>{cue.kind} <time dateTime={cue.date}>{cue.date}</time></span>
      : <span className="sr-only">{cue.detail}</span>}
    {other !== cue.date && calendarDay(other) !== null && <span className="date-secondary">{cue.kind === 'Collection' ? 'Use by' : 'Collection'} <time dateTime={other}>{other}</time></span>}
  </span>;
}

export function ClockBasis({ today }: { today: string }) {
  return <p className="clock-basis">Calendar cues use your browser-local date at view opening: <time dateTime={today}>{today}</time>.
    {' '}Reload to update. Dates alone do not establish food safety; these are not spoilage countdowns.</p>;
}

// The parent keys this component by digest and record state. Clipboard state is
// local feedback only: it cannot attest to publication, integrity or custody.
export function DigestCustody({ plan, mode }: { plan: Plan; mode: Mode }) {
  const [copyState, setCopyState] = useState<'idle' | 'copying' | 'copied' | 'failed'>('idle');
  const missingReason = `${useId()}-missing-digest`;
  const label = plan.recorded ? mode === 'sandbox' ? 'Sandbox record · server reported' : 'Published record · server reported'
    : 'Draft · approval still required';
  async function copy() {
    setCopyState('copying');
    try { await navigator.clipboard.writeText(plan.digest); setCopyState('copied'); }
    catch { setCopyState('failed'); }
  }
  return <div className="digest-custody">
    <div className="custody-heading"><span className="custody-pill">{label}</span>
      <button type="button" className="secondary digest-copy" disabled={copyState === 'copying' || !plan.digest} aria-describedby={plan.digest ? undefined : missingReason} onClick={copy}>
        {copyState === 'copying' ? 'Copying digest…' : 'Copy digest'}
      </button></div>
    {!plan.digest && <p className="small-note" id={missingReason}>The server has not supplied a digest to copy.</p>}
    <label className="digest-label">Content digest (SHA-256)<input className="digest-value" aria-label="Approval content digest" readOnly value={plan.digest}/></label>
    <p className="digest-explanation">Binds the record text, address and network. Not a Merkle proof or independently verified custody.</p>
    {copyState === 'copied' && <p role="status" className="copy-feedback">Digest copied. Record status is unchanged.</p>}
    {copyState === 'failed' && <p role="status" className="copy-feedback">Clipboard unavailable. Select and copy the digest field above.</p>}
  </div>;
}
