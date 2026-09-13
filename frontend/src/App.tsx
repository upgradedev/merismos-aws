import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from './api';
import { AddOffer } from './AddOffer';
import { Offers } from './components';
import { History, Pickups } from './Pickups';
import { Dashboard } from './Dashboard';
import { DispatchWorkspace } from './DispatchWorkspace';
import { Records } from './Records';
import { ClockBasis } from './DispatchEvidence';
import { localCalendarDate } from './dispatch';
import { parseRoute, routeLink } from './routes';
import type { Mode, Workspace } from './types';
import { readPreference, storageBlocked, writePreference } from './storage';
import { SessionRecovery } from './SessionRecovery';
import { LandingPage } from './LandingPage';
import { UserJourneysView } from './UserJourneysView';
import { ArchitectureView } from './ArchitectureView';
import { GtmImpactView } from './GtmImpactView';

function currentAddress() {
  const previous = history.state?.merismosContext;
  const current = readPreference('merismos.session.context');
  if (previous && current && previous !== current) return '/previous-workspace';
  if (location.hash && location.hash.length > 1) return location.hash.slice(1);
  const search = new URLSearchParams(location.search);
  const page = search.get('page') || search.get('tab');
  if (page) {
    const clean = page.startsWith('/') ? page : '/' + page;
    const offer = search.get('offer');
    const pickup = search.get('pickup');
    const params = new URLSearchParams();
    if (offer) params.set('offer', offer);
    if (pickup) params.set('pickup', pickup);
    return `${clean}${params.size ? `?${params}` : ''}`;
  }
  return '';
}

export function App() {
  const [mode, setMode] = useState<Mode>(() => readPreference('merismos.mode') === 'live' ? 'live' : 'sandbox');
  const [address, setAddress] = useState(currentAddress);
  const [selection, setSelection] = useState(() => parseRoute(currentAddress()).offer);
  const [sessionEpoch, setSessionEpoch] = useState(0);
  const [restarted, setRestarted] = useState(false);
  const [confirmRestart, setConfirmRestart] = useState(false);
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
    setExpired(e instanceof api.SessionError || e instanceof api.ApiError && [401, 403, 410].includes(e.status));
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
    const navigate = () => {
      const next = currentAddress(); setAddress(next);
      const nextOffer = parseRoute(next).offer; if (nextOffer) setSelection(nextOffer);
      if (next !== '/previous-workspace') history.replaceState({ ...history.state, merismosContext: readPreference('merismos.session.context'), merismosSandboxVisited: !!readPreference('merismos.session.seen') }, '');
    };
    window.addEventListener('hashchange', navigate);
    window.addEventListener('popstate', navigate);
    return () => {
      window.removeEventListener('hashchange', navigate);
      window.removeEventListener('popstate', navigate);
    };
  }, []);
  useEffect(() => {
    if (data && mode === 'sandbox' && currentAddress() !== '/previous-workspace') history.replaceState({ ...history.state, merismosContext: readPreference('merismos.session.context'), merismosSandboxVisited: true }, '');
  }, [data, mode]);
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
    history.replaceState(history.state, '', next);
    setAddress(next.slice(1));
  }, [selected]);
  function changeMode(next: Mode) { writePreference('merismos.mode', next); setMode(next); }
  async function restart() {
    if (mutationLock.current || loading || mode !== 'sandbox') return;
    const current = ++generation.current;
    mutationLock.current = true; setBusy(true);
    try {
      const next = await api.startIsolatedWorkspace();
      if (current !== generation.current) return;
      retry.current = null; setSelection(''); setSessionEpoch(value => value + 1);
      const destination = route.offer && !next.offers.some(row => row.offer.id === route.offer) ? location.hash : '#/dashboard';
      history.replaceState({ merismosContext: readPreference('merismos.session.context'), merismosSandboxVisited: true }, '', destination);
      setAddress(destination.slice(1)); setData(next); setError(''); setExpired(false); setActionBlocked(false);
      setObservedAt(new Date().toLocaleString()); setRestarted(true);
    } catch (e) { if (current === generation.current) report(e); }
    finally { mutationLock.current = false; setBusy(false); }
  }
  const navigateTo = useCallback((dest: string) => {
    const next = routeLink(dest, { offer: selected, pickup: route.pickup });
    history.pushState({ ...history.state, merismosContext: readPreference('merismos.session.context'), merismosSandboxVisited: true }, '', next);
    setAddress(next.slice(1));
  }, [selected, route.pickup]);
  const nav = [
    ['/dashboard', 'Dashboard', 'dashboard'],
    ['/workspace', 'Decide', 'workspace'],
    ['/pickups', 'Pickups', 'pickups'],
    ['/records', 'Records', 'records'],
    ['/history', 'History', 'history']
  ];
  const unavailable = busy || loading || actionBlocked || expired || (!!error && route.page !== 'intake');
  return <div className="app-shell"><a href="#main" className="skip-link" onClick={e => { e.preventDefault(); document.getElementById('main')?.focus(); }}>Skip to main content</a>
    <aside className="sidebar"><a href={routeLink('/dashboard', { offer: selected, pickup: route.pickup })} className="brand"><span className="brand-icon" aria-hidden="true">μ</span><span>merismos<small>FOOD ALLOCATION</small></span></a><div className="network-label"><span aria-hidden="true">◉</span> Kypseli network<small>Five synthetic community organisations</small></div>
      <nav aria-label="Main navigation">{nav.map(([path, label, page]) => <a href={routeLink(path, { offer: selected, pickup: route.pickup })} key={path} onClick={e => { e.preventDefault(); navigateTo(path); }} aria-current={route.page === page || page === 'workspace' && route.page === 'intake' ? 'page' : undefined}>{label}</a>)}</nav>
      <div className="sidebar-bottom"><p>Consider the split.<br/>Keep the reasons.<br/>Close the collection.</p><a href="#/overview">Overview</a></div></aside>
    <div className="workspace"><header className="topbar"><span className="date-chip">Today · <time dateTime={today}>{today}</time></span><div className="sr-only"><ClockBasis today={today}/></div><div className="mode-control"><label htmlFor="mode">Workspace</label><select id="mode" value={mode} onChange={e => changeMode(e.target.value as Mode)} disabled={busy} aria-describedby={busy ? 'mode-reason' : undefined}><option value="sandbox">My sandbox</option><option value="live">Shared demo records (read-only)</option></select>{busy && <small id="mode-reason">Mode switch paused while a change is saved.</small>}</div></header>
      <div className="demo-banner"><span className="demo-dot" aria-hidden="true"/><strong>Synthetic demo</strong><span>{mode === 'sandbox' ? 'Sandbox · synthetic data · nothing is published' : 'Shared demo records · read-only · synthetic data'}</span></div>
      <main id="main" tabIndex={-1}>
        {error && !['landing', 'journeys', 'architecture', 'impact'].includes(route.page) && (actionBlocked ? <SessionRecovery key={`recovery-${sessionEpoch}`} message={error} sessionUnavailable={expired} mode={mode} busy={loading || busy} hasSnapshot={!!data} refresh={() => void refresh()} restart={() => void restart()}/> : <div role="alert" className="error"><h2>That action could not be completed</h2><p>{error}</p><p>Correct the highlighted information and submit the offer again. The rejected intake was not saved.</p><button className="secondary" disabled={loading || busy} aria-describedby={loading || busy ? 'review-reason' : undefined} onClick={() => void refresh()}>Refresh and review</button>{(loading || busy) && <p id="review-reason" className="small-note">Refresh paused while the workspace loads or saves.</p>}</div>)}
        {restarted && <p role="status" className="success-note">New isolated workspace ready. Previous offers and actions were not restored or repeated. Start with a sample or add a new donation.</p>}
        {actionBlocked && data && <p className="notice">Refresh failed; saved view may be stale. Review the current server state before acting.</p>}
        {busy && <p role="status" className="working">Saving through the backend. Please wait before making another change.</p>}
        {data?.operations?.filter(operation => operation.status === 'pending').map(operation => <div className="notice" key={operation.id}><p>{operation.offer_id}: {operation.action} outcome pending or unknown. Refreshing only reads the workspace. Recovery checks this exact attempt without issuing a second publication.</p><button disabled={unavailable || !data.can_write} aria-describedby={unavailable && data.can_write ? `reconcile-${operation.id}` : undefined} onClick={() => void mutate(operation.offer_id, 'recover', {operation_id: operation.id})}>Reconcile recorded outcome</button>{unavailable && data.can_write && <p className="small-note" id={`reconcile-${operation.id}`}>Reconcile paused while a change is saved or an error needs a refresh.</p>}{!data.can_write && <p>{data.authorization_note} Ask the coordinator to reconcile this attempt.</p>}</div>)}
        {storageBlocked() && <p className="notice">Browser storage is unavailable. This session works in this tab, but reloading may lose its handle.</p>}
        {loading && !data && !['landing', 'journeys', 'architecture', 'impact'].includes(route.page) && <div className="loading" role="status"><span className="spinner" aria-hidden="true"/>Loading your coordinator workspace…</div>}
        {route.page === 'landing' ? <LandingPage data={data} onLaunchCockpit={() => navigateTo('/dashboard')} onNavigate={navigateTo}/> : route.page === 'journeys' ? <UserJourneysView data={data}/> : route.page === 'architecture' ? <ArchitectureView/> : route.page === 'impact' ? <GtmImpactView/> : (data && <div key={sessionEpoch}>{route.path === '/previous-workspace' ? <div className="empty"><h1>This address belongs to the previous workspace</h1><p>The new session cannot restore the old offer or its approvals. No action was repeated.</p><a href="#/dashboard">Open the current dashboard</a></div> : route.page === 'dashboard' ? <Dashboard data={data} today={today} unit={route.unit} selected={selected} pickup={route.pickup}/> : route.page === 'workspace' ? <DispatchWorkspace key={`${mode}-${route.filter}-${route.unit}`} data={data} selected={selected} filter={route.filter} unit={route.unit} today={today} busy={unavailable} mutate={mutate} pickup={route.pickup} onPickupChange={selectPickup}/> : route.page === 'pickups' ? <Pickups data={data} busy={unavailable} mutate={mutate}/> : route.page === 'history' ? <History data={data} selected={selected} pickup={route.pickup}/> : route.page === 'intake' ? <AddOffer key={mode} data={data} busy={unavailable} mutate={mutate}/> : route.path === '/offers' ? <Offers key={mode} data={data}/> : route.page === 'records' ? <Records data={data} route={route} selected={selected} today={today}/> : <div className="empty"><h1>Page not found</h1><p>This address is not part of the workspace. <a href={routeLink('/workspace', { offer: selected, pickup: route.pickup })}>Open workspace</a>.</p></div>}</div>)}
      </main><footer><span>MERISMOS</span><span className="footer-refresh"><button className="text-button" onClick={() => void refresh()} disabled={loading || busy} aria-describedby={loading || busy ? 'refresh-reason' : undefined}>Refresh workspace</button>{(loading || busy) && <small id="refresh-reason">Refresh paused while the workspace loads or saves.</small>}</span><details className="about-demo"><summary>About this demo</summary><p>Five synthetic organisations and invented donations. The public sandbox runs a Strands agent loop with scripted responses: no model call, no message, no publication. Time saved and food rescued are not measured.</p><p className="small-note">{data?.provider || 'Connecting to the coordinator service'}{observedAt && <span className="observed-at">Snapshot as of {observedAt}{actionBlocked ? ' · Refresh failed' : loading ? ' · Refreshing' : ''}</span>}</p><ul><li><a href="#/overview">Overview</a></li><li><a href="#/journeys">How a donation moves</a></li><li><a href="#/architecture">AWS architecture</a></li><li><a href="#/impact">Impact and limits</a></li><li><a href="/acceptance.html">Automated acceptance</a></li><li><a href="/UAT.testbook.html">Acceptance testbook</a></li></ul><p className="small-note">Automated CI results; human acceptance is not run.</p>{mode === 'sandbox' && !actionBlocked && (confirmRestart ? <div className="form-actions"><button onClick={() => { setConfirmRestart(false); void restart(); }}>Yes, start fresh</button><button className="secondary" onClick={() => setConfirmRestart(false)}>No, keep this sandbox</button></div> : <button className="secondary" onClick={() => setConfirmRestart(true)}>Start over in a new sandbox</button>)}</details></footer></div></div>;
}
