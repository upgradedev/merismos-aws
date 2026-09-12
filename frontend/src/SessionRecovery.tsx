import { useState } from 'react';
import type { Mode } from './types';

export function SessionRecovery({ message, sessionUnavailable, mode, busy, hasSnapshot, refresh, restart }: {
  message: string; sessionUnavailable: boolean; mode: Mode; busy: boolean; hasSnapshot: boolean;
  refresh: () => void; restart: () => void;
}) {
  const [confirm, setConfirm] = useState(false);
  return <section role="alert" className="error">
    <h2>{sessionUnavailable ? 'Your previous workspace needs attention' : 'That action could not be completed'}</h2>
    <p>{message}</p>
    {sessionUnavailable && <p>The session may have expired, be unknown or have had access revoked. The service does not distinguish all of these cases. A missing handle cannot recover a workspace by offer name.</p>}
    <p>Actions are paused. Refresh and review the current state before retrying. Refresh only reads using the saved session; it does not repeat an approval or publication.</p>
    {hasSnapshot && <p>The last loaded offer and its context remain below for reference. They may be stale and cannot authorize another action.</p>}
    <button className="secondary" disabled={busy} onClick={refresh}>Refresh and review</button>
    {mode === 'sandbox' && <div className="recovery-choice"><h3>Continue in a new isolated demo workspace</h3>
      <p>Your old session is not changed or deleted. A new workspace starts with synthetic sample offers. Previous offers, approvals, collection tasks and unsent edits are not copied. The old handle is retained in this browser where storage is available; this does not restore expired or revoked access.</p>
      {!confirm ? <button className="secondary" disabled={busy} onClick={() => setConfirm(true)}>{sessionUnavailable ? 'Start a new sandbox' : 'Start a separate sandbox'}</button> : <><p>Start over with a new isolated session and leave the previous offer context?</p><div className="form-actions"><button disabled={busy} onClick={restart}>Create isolated workspace</button><button className="secondary" disabled={busy} onClick={() => setConfirm(false)}>Keep previous workspace</button></div></>}
    </div>}
  </section>;
}
