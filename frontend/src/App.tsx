import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from './api';
import { AddOffer } from './AddOffer';
import { Offers } from './components';
import { History, Pickups } from './Pickups';
import { Dashboard } from './Dashboard';
import { DispatchWorkspace } from './DispatchWorkspace';
import { Records } from './Records';
import { localCalendarDate } from './dispatch';
import { parseRoute, routeLink } from './routes';
import type { Mode, Workspace } from './types';
import { readPreference, removePreference, storageBlocked, writePreference } from './storage';

export function App() {
  const [mode, setMode] = useState<Mode>(() => readPreference('merismos.mode') === 'live' ? 'live' : 'sandbox');
  const [address, setAddress] = useState(() => location.hash.slice(1));
  const [selection, setSelection] = useState(() => parseRoute(location.hash.slice(1)).offer);
  const [today] = useState(localCalendarDate);
  const [data, setData] = useState<Workspace>();
  const [observedAt, setObservedAt] = useState('');
  const [error, setError] = useState('');
  const [actionBlocked, setActionBlocked] = useState(false);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const mutationLock = useRef(false);
  const retry = useRef<{ signature: string; id: string } | null>(null);
  const route = parseRoute(address);
  const previousPage = useRef(route.page);
  const selected = route.offer || selection || data?.offers[0]?.offer.id || '';
  const report = useCallback((e: unknown, mustRefresh = true) => {
    setError(e instanceof Error ? e.message : 'The workspace could not be loaded. Try refreshing.');
    setActionBlocked(mustRefresh);
    setExpired(e instanceof api.ApiError && [401, 410].includes(e.status));
  }, []);
  const refresh = useCallback(async () => {
    if (mutationLock.current) return;
    const current = ++generation.current;
    setLoading(true);
    try {
      const next = await api.loadWorkspace(mode);
      if (current === generation.current) {
        if (next.operations?.some(operation => operation.id === retry.current?.id && operation.status === 'failed')) retry.current = null;
        setData(next); setError(''); setActionBlocked(false); setExpired(false); setObservedAt(new Date().toLocaleString());
      }
    } catch (e) { if (current === generation.current) report(e); }
    finally { if (current === generation.current) setLoading(false); }
  }, [mode, report]);
  useEffect(() => { setData(undefined); setObservedAt(''); setError(''); setExpired(false); retry.current = null; void refresh(); return () => { generation.current++; }; }, [refresh]);
  useEffect(() => {
    const navigate = () => { const next = location.hash.slice(1); setAddress(next); const nextOffer = parseRoute(next).offer; if (nextOffer) setSelection(nextOffer); };
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);
  useEffect(() => {
    document.title = `Merismos · ${route.page[0].toUpperCase()}${route.page.slice(1)}`;
    if (previousPage.current !== route.page) {
      const heading = document.querySelector<HTMLElement>('#main h1');
      if (heading) { heading.tabIndex = -1; heading.focus(); }
      previousPage.current = route.page;
    }
  }, [route.page]);
  const running = data?.offers.some(o => o.status === 'running');
  useEffect(() => { if (!running || busy || error || loading) return; const timer = setTimeout(() => void refresh(), 5000); return () => clearTimeout(timer); }, [running, busy, error, loading, refresh]);
  async function mutate(offer: string, kind: string, payload: Record<string, unknown> = {}) {
    if (!data || mutationLock.current || loading || expired || actionBlocked || (error && kind !== 'add') || !data.can_write) return false;
    const signature = JSON.stringify({ offer, kind, payload, mode });
    if (retry.current?.signature !== signature) retry.current = { signature, id: crypto.randomUUID() };
    const current = ++generation.current;
    mutationLock.current = true;
    setBusy(true); setError('');
    try {
      const next = await api.action(data, offer, kind, payload, retry.current.id);
      if (current !== generation.current) return false;
      setData(next); setObservedAt(new Date().toLocaleString()); retry.current = null;
      if (kind === 'add' || kind === 'import') { const added = next.offers.find(row => !data.offers.some(old => old.offer.id === row.offer.id)); if (added) location.hash = `/offers/${added.offer.id}`; }
      return true;
    } catch (e) { if (current === generation.current) { if (kind === 'import') retry.current = null; report(e, !(kind === 'add' && e instanceof api.ApiError && e.status === 400)); } return false; }
    finally { mutationLock.current = false; setBusy(false); }
  }
  const selectPickup = useCallback((pickup: string) => {
    const current = parseRoute(location.hash.slice(1));
    if (current.page !== 'workspace') return;
    const next = routeLink('/workspace', { ...current, offer: selected, pickup });
    // A default or changed task is view context, not a new page in the back stack.
    history.replaceState(null, '', next);
    setAddress(next.slice(1));
  }, [selected]);
  function changeMode(next: Mode) { writePreference('merismos.mode', next); setMode(next); }
  function restart() { removePreference('merismos.session'); retry.current = null; setData(undefined); setExpired(false); void refresh(); }
  const nav = [['/dashboard', 'Dashboard', '01', 'dashboard'], ['/workspace', 'Workspace', '02', 'workspace'], ['/records', 'Records', '03', 'records'], ['/history', 'History', '04', 'history']];
  const unavailable = busy || loading || actionBlocked || expired || (!!error && route.page !== 'intake');
  return <div className="app-shell"><a href="#main" className="skip-link" onClick={e => { e.preventDefault(); document.getElementById('main')?.focus(); }}>Skip to main content</a>
    <aside className="sidebar"><a href={routeLink('/dashboard', { offer: selected, pickup: route.pickup })} className="brand"><span className="brand-icon" aria-hidden="true">μ</span><span>merismos<small>CIVIC DISPATCH</small></span></a><div className="network-label"><span aria-hidden="true">◉</span> Kypseli network<small>Five synthetic community organisations</small></div>
      <nav aria-label="Main navigation">{nav.map(([path, label, number, page]) => <a href={routeLink(path, { offer: selected, pickup: route.pickup })} key={path} aria-current={route.page === page || page === 'workspace' && ['pickups', 'intake'].includes(route.page) ? 'page' : undefined}><span aria-hidden="true">{number}</span>{label}</a>)}</nav>
      <div className="sidebar-bottom"><p>Consider the split.<br/>Keep the reasons.<br/>Close the collection.</p><a href={routeLink('/pickups', { offer: selected, pickup: route.pickup })}>Collection tasks</a><a href="/UAT.testbook.html" target="_blank" rel="noreferrer">Acceptance testbook ↗</a><a href="https://efnt6e0kv7.execute-api.eu-west-1.amazonaws.com/offer/offer-4471" target="_blank" rel="noreferrer">Legacy offer view ↗</a></div></aside>
    <div className="workspace"><header className="topbar"><span>Community coordination</span><div className="mode-control"><label htmlFor="mode">Workspace</label><select id="mode" value={mode} onChange={e => changeMode(e.target.value as Mode)} disabled={busy}><option value="sandbox">Sandbox</option><option value="live">Live records</option></select></div></header>
      <div className="demo-banner"><span className="demo-dot" aria-hidden="true"/><strong>Synthetic demo</strong><span>{mode === 'sandbox' ? 'Your isolated sandbox. No public publication, real collection or model network call.' : 'Live backend view of synthetic demonstrations. Public records remain separate from sandbox activity.'}</span></div>
      <main id="main" tabIndex={-1}><div className="workspace-tools"><span className="small-note">{data?.provider || 'Connecting to the coordinator service'}{observedAt && <span className="observed-at">Snapshot as of {observedAt}{actionBlocked ? ' · Refresh failed; saved view may be stale' : loading ? ' · Refreshing' : ''}</span>}</span><button className="text-button" onClick={() => void refresh()} disabled={loading || busy}>Refresh workspace</button></div>
        {error && <div role="alert" className="error"><h2>That action could not be completed</h2><p>{error}</p><p>{actionBlocked ? 'Actions are paused. Refresh and review the current state before retrying.' : 'Correct the highlighted information and submit the offer again. The rejected intake was not saved.'}</p><button className="secondary" disabled={loading || busy} onClick={expired && mode === 'sandbox' ? restart : () => void refresh()}>{expired && mode === 'sandbox' ? 'Start a new sandbox' : 'Refresh and review'}</button></div>}
        {busy && <p role="status" className="working">Saving through the backend. Please wait before making another change.</p>}
        {data?.operations?.filter(operation => operation.status === 'pending').map(operation => <div className="notice" key={operation.id}><p>{operation.offer_id}: {operation.action} outcome pending or unknown. Refreshing only reads the workspace. Recovery checks this exact attempt without issuing a second publication.</p><button disabled={unavailable || !data.can_write} onClick={() => void mutate(operation.offer_id, 'recover', {operation_id: operation.id})}>Reconcile recorded outcome</button>{!data.can_write && <p>{data.authorization_note} Ask the coordinator to reconcile this attempt.</p>}</div>)}
        {storageBlocked() && <p className="notice">Browser storage is unavailable. This session works in this tab, but reloading may lose its handle.</p>}
        {error && mode === 'sandbox' && !expired && <p className="small-note">To recover from an unknown action outcome, you can <button className="text-button" onClick={restart} disabled={busy || loading}>Start a separate sandbox</button>. Your old session is not changed or deleted.</p>}
        {loading && !data && <div className="loading" role="status"><span className="spinner" aria-hidden="true"/>Loading your coordinator workspace…</div>}
        {data && (route.page === 'dashboard' ? <Dashboard data={data} today={today} unit={route.unit} selected={selected} pickup={route.pickup}/> : route.page === 'workspace' ? <DispatchWorkspace key={`${mode}-${route.filter}-${route.unit}`} data={data} selected={selected} filter={route.filter} unit={route.unit} today={today} busy={unavailable} mutate={mutate} pickup={route.pickup} onPickupChange={selectPickup}/> : route.page === 'pickups' ? <Pickups data={data} busy={unavailable} mutate={mutate}/> : route.page === 'history' ? <History data={data} selected={selected} pickup={route.pickup}/> : route.page === 'intake' ? <AddOffer key={mode} data={data} busy={unavailable} mutate={mutate}/> : route.path === '/offers' ? <Offers key={mode} data={data}/> : route.page === 'records' ? <Records data={data} route={route} selected={selected} today={today}/> : <div className="empty"><h1>Page not found</h1><p>This address is not part of the workspace. <a href={routeLink('/workspace', { offer: selected, pickup: route.pickup })}>Open workspace</a>.</p></div>)}
      </main><footer>MERISMOS <span>Allocation is a decision. Collection is a separate fact. <a href="/acceptance.html">Automated acceptance</a></span></footer></div></div>;
}
