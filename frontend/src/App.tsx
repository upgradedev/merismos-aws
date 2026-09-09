import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from './api';
import { AddOffer } from './AddOffer';
import { Offers } from './components';
import { OfferDetail } from './OfferDetail';
import { History, Pickups } from './Pickups';
import type { Mode, Workspace } from './types';
import { readPreference, removePreference, storageBlocked, writePreference } from './storage';

export function App() {
  const [mode, setMode] = useState<Mode>(() => readPreference('merismos.mode') === 'live' ? 'live' : 'sandbox');
  const [route, setRoute] = useState(() => location.hash.slice(1) || '/offers');
  const [data, setData] = useState<Workspace>();
  const [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const retry = useRef<{signature: string; id: string} | null>(null);
  const report = useCallback((e: unknown) => {
    setError(e instanceof Error ? e.message : 'The workspace could not be loaded. Try refreshing.');
    setExpired(e instanceof api.ApiError && [401, 410].includes(e.status));
  }, []);
  const refresh = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true); setError('');
    try { const next = await api.loadWorkspace(mode); if (current === generation.current) setData(next); }
    catch (e) { if (current === generation.current) report(e); }
    finally { if (current === generation.current) setLoading(false); }
  }, [mode, report]);
  useEffect(() => { setData(undefined); retry.current = null; void refresh(); return () => { generation.current++; }; }, [refresh]);
  useEffect(() => { const navigate = () => setRoute(location.hash.slice(1) || '/offers'); window.addEventListener('hashchange', navigate); return () => window.removeEventListener('hashchange', navigate); }, []);
  useEffect(() => { document.title = `Merismos · ${route.startsWith('/pickups') ? 'Pickups' : route.startsWith('/history') ? 'History' : 'Offers'}`; }, [route]);
  const running = data?.offers.some(o => o.status === 'running');
  useEffect(() => { if (!running || busy) return; const timer = setInterval(() => void refresh(), 5000); return () => clearInterval(timer); }, [running, busy, refresh]);
  async function mutate(offer: string, kind: string, payload: Record<string, unknown> = {}) {
    if (!data || busy) return false;
    const signature = JSON.stringify({ offer, kind, payload, mode });
    if (retry.current?.signature !== signature) retry.current = { signature, id: crypto.randomUUID() };
    const current = ++generation.current;
    setBusy(true); setError('');
    try { const next = await api.action(data, offer, kind, payload, retry.current.id); if (current === generation.current) { setData(next); retry.current = null; if (kind === 'add') { const added = next.offers.find(row => !data.offers.some(old => old.offer.id === row.offer.id)); if (added) location.hash = `/offers/${added.offer.id}`; } } return true; }
    catch (e) { if (current === generation.current) report(e); return false; }
    finally { setBusy(false); }
  }
  function changeMode(next: Mode) { writePreference('merismos.mode', next); setMode(next); }
  function restart() { removePreference('merismos.session'); retry.current = null; setData(undefined); setExpired(false); void refresh(); }
  const offerId = route.startsWith('/offers/') ? route.slice(8) : '';
  const nav = [['/offers', 'Offers', '01'], ['/pickups', 'Pickups', '02'], ['/history', 'Published history', '03']];
  return <div className="app-shell"><a href="#main" className="skip-link" onClick={e => { e.preventDefault(); document.getElementById('main')?.focus(); }}>Skip to main content</a><aside className="sidebar"><a href="#/offers" className="brand"><span className="brand-icon" aria-hidden="true">μ</span><span>merismos<small>THE COORDINATOR WORKSPACE</small></span></a><div className="network-label"><span aria-hidden="true">◉</span> Kypseli network<small>Five synthetic community organisations</small></div><nav aria-label="Main navigation">{nav.map(([path, label, number]) => <a href={`#${path}`} key={path} aria-current={route.startsWith(path) ? 'page' : undefined}><span aria-hidden="true">{number}</span>{label}</a>)}</nav><div className="sidebar-bottom"><p>Consider the split.<br/>Keep the reasons.<br/>Close the collection.</p><a href="/UAT.testbook.html" target="_blank" rel="noreferrer">Acceptance testbook ↗</a><a href="https://efnt6e0kv7.execute-api.eu-west-1.amazonaws.com/offer/offer-4471" target="_blank" rel="noreferrer">Legacy offer view ↗</a></div></aside><div className="workspace"><header className="topbar"><span>Community coordination</span><div className="mode-control"><label htmlFor="mode">Workspace</label><select id="mode" value={mode} onChange={e => changeMode(e.target.value as Mode)} disabled={busy}><option value="sandbox">Sandbox</option><option value="live">Live records</option></select></div></header><div className="demo-banner"><span className="demo-dot" aria-hidden="true"/><strong>Synthetic demo</strong><span>{mode === 'sandbox' ? 'Your isolated sandbox. No public publication, real collection or model network call.' : 'Live backend view of synthetic demonstrations. Public records remain separate from sandbox activity.'}</span></div><main id="main" tabIndex={-1}>
      <div className="workspace-tools"><span className="small-note">{data?.provider || 'Connecting to the coordinator service'}</span><button className="text-button" onClick={() => void refresh()} disabled={loading || busy}>Refresh workspace</button></div>
      {error && <div role="alert" className="error"><h2>That action could not be completed</h2><p>{error}</p><button className="secondary" onClick={expired ? restart : () => void refresh()}>{expired ? 'Start a new sandbox' : 'Refresh and review'}</button></div>}
      {busy && <p role="status" className="working">Saving through the backend. Please wait before making another change.</p>}
      {storageBlocked() && <p className="notice">Browser storage is unavailable. This session works in this tab, but reloading may lose its handle.</p>}
      {error && mode === 'sandbox' && !expired && <p className="small-note">To recover from an unknown action outcome, you can <button className="text-button" onClick={restart} disabled={busy}>Start a separate sandbox</button>. Your old session is not changed or deleted.</p>}
      {loading && !data && <div className="loading" role="status"><span className="spinner" aria-hidden="true"/>Loading your coordinator workspace…</div>}
      {data && (route === '/pickups' ? <Pickups data={data} busy={busy} mutate={mutate}/> : route === '/history' ? <History data={data}/> : route === '/offers/new' ? <AddOffer data={data} busy={busy} mutate={mutate}/> : offerId ? <OfferDetail key={`${mode}-${offerId}-${data.offers.find(o => o.offer.id === offerId)?.result.run_id}`} row={data.offers.find(o => o.offer.id === offerId)} data={data} busy={busy} mutate={mutate}/> : route === '/offers' ? <Offers data={data}/> : <div className="empty"><h1>Page not found</h1><p>This address is not part of the workspace. <a href="#/offers">Open offers</a>.</p></div>)}
    </main><footer>MERISMOS <span>Allocation is a decision. Collection is a separate fact.</span></footer></div></div>;
}
