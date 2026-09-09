import { useState } from 'react';
import { calendarDay, dateCue } from './dispatch';
import type { Mode, Offer, Plan } from './types';

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
  const label = plan.recorded ? mode === 'sandbox' ? 'Sandbox record · server reported' : 'Published record · server reported'
    : 'Draft · approval still required';
  async function copy() {
    setCopyState('copying');
    try { await navigator.clipboard.writeText(plan.digest); setCopyState('copied'); }
    catch { setCopyState('failed'); }
  }
  return <div className="digest-custody">
    <div className="custody-heading"><span className="custody-pill">{label}</span>
      <button type="button" className="secondary digest-copy" disabled={copyState === 'copying' || !plan.digest} onClick={copy}>
        {copyState === 'copying' ? 'Copying digest…' : 'Copy digest'}
      </button></div>
    <label className="digest-label">Content digest (SHA-256)<input className="digest-value" aria-label="Approval content digest" readOnly value={plan.digest}/></label>
    <p className="digest-explanation">Binds the record text, address and network. Not a Merkle proof or independently verified custody.
      {mode === 'sandbox' ? ' Sandbox records are not public publications.' : ''}</p>
    {!plan.digest && <p className="small-note">The server has not supplied a digest to copy.</p>}
    {copyState === 'copied' && <p role="status" className="copy-feedback">Digest copied. Record status is unchanged.</p>}
    {copyState === 'failed' && <p role="status" className="copy-feedback">Clipboard unavailable. Select and copy the digest field above.</p>}
  </div>;
}
