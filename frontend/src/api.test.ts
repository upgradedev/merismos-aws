import { beforeEach, describe, expect, it, vi } from 'vitest';
import { action, ApiError, loadWorkspace, previewCsv, request, session, SessionError, startIsolatedWorkspace } from './api';
import { removePreference } from './storage';
import { workspace } from './test/fixtures';

describe('HTTP and session boundary', () => {
  beforeEach(() => { localStorage.setItem('merismos.session', 'existing-test-session'); });
  it('deduplicates session creation and stores only the handle', async () => {
    removePreference('merismos.session');
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({session:'handle'})));
    vi.stubGlobal('fetch', fetcher);
    expect(await Promise.all([session(), session()])).toEqual(['handle','handle']);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(await session()).toBe('handle');
    expect(localStorage.getItem('merismos.session')).toBe('handle');
  });
  it('loads mode and sends exact action inputs once', async () => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(workspace()))));
    vi.stubGlobal('fetch', fetcher);
    localStorage.setItem('merismos.session','sandbox-handle');
    await loadWorkspace('sandbox'); await loadWorkspace('live');
    await action(workspace(),'offer-4471','approve',{digest:'exact',consent:true},'request-id');
    await action({...workspace(),mode:'live'},'','add',{form:{title:'Bread'}},'request-id-2');
    expect(fetcher.mock.calls[0][0]).toBe('/api/workspace?mode=sandbox');
    expect(fetcher.mock.calls[2][1].headers['X-Merismos-Session']).toBe('sandbox-handle');
    expect(JSON.parse(fetcher.mock.calls[2][1].body)).toMatchObject({digest:'exact',consent:true,request_id:'request-id',version:1});
    expect(fetcher.mock.calls[3][0]).toBe('/api/offers/new');
    expect(fetcher.mock.calls[3][1].headers['X-Merismos-Session']).toBe('');
  });
  it.each([[409,{detail:'Stale plan'},'Stale plan'],[500,{},'The request failed. Try refreshing.']])('reports HTTP %s with actionable text', async (status, body, message) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body),{status:status as number})));
    await expect(request('/api')).rejects.toThrow(message as string);
  });
  it('rejects non-JSON successes and surfaces network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>gateway</html>')));
    await expect(request('/api')).rejects.toBeInstanceOf(ApiError);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    await expect(request('/api')).rejects.toThrow('offline');
  });
  it('bounds a hung request without retrying a mutation', async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn((_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new Error('aborted')))));
    vi.stubGlobal('fetch', fetcher);
    const pending = expect(request('/api', {method:'POST'})).rejects.toThrow('timed out');
    await vi.advanceTimersByTimeAsync(35_000); await pending;
    expect(fetcher).toHaveBeenCalledTimes(1); vi.useRealTimers();
  });
  it('honors caller cancellation', async () => {
    vi.stubGlobal('fetch', vi.fn((_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new Error('aborted'))))));
    const controller = new AbortController();
    const pending = expect(request('/api', {signal:controller.signal})).rejects.toThrow('cancelled');
    controller.abort(); await pending;
  });
  it('an already cancelled preview keeps the fetch signal cancelled', async () => {
    const controller = new AbortController(); controller.abort();
    const fetcher = vi.fn((_url, init) => { expect(init.signal.aborted).toBe(true); return Promise.reject(new Error('abort')); });
    vi.stubGlobal('fetch', fetcher);
    await expect(previewCsv({...workspace(), mode: 'live'}, 'csv', controller.signal)).rejects.toThrow('cancelled');
  });
  it('files selected rows sequentially through governed intake with new versions and stable per-row ids', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({...workspace(), version: 3}))).mockResolvedValueOnce(new Response(JSON.stringify({...workspace(), version: 5})));
    vi.stubGlobal('fetch', fetcher);
    const result = await action(workspace(), '', 'import', {csv: 'data', csv_digest: 'sha', rows: [2, 5]}, 'batch');
    expect(result.version).toBe(5);
    expect(fetcher.mock.calls.map(call => call[0])).toEqual(['/api/offers/new', '/api/offers/new']);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({row: 2, version: 1, request_id: 'batch-2', csv_digest: 'sha'});
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({row: 5, version: 3, request_id: 'batch-5'});
  });
  it.each([400, 409, 502])('a partial CSV import stops on HTTP %s and reports confirmed progress without retry', async status => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({...workspace(), version: 3}))).mockResolvedValueOnce(new Response(JSON.stringify({detail: 'Row refused or outcome unknown'}), {status}));
    vi.stubGlobal('fetch', fetcher);
    await expect(action(workspace(), '', 'import', {csv: 'data', csv_digest: 'sha', rows: [2, 3, 4]}, 'batch')).rejects.toThrow('after 1 confirmed rows. CSV row 3');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it.each([401, 403, 404, 410])('classifies a refused workspace read (%s) without replacing its handle', async status => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({detail: 'Workspace unavailable'}), {status}));
    vi.stubGlobal('fetch', fetcher);
    await expect(loadWorkspace('sandbox')).rejects.toBeInstanceOf(SessionError);
    expect(localStorage.getItem('merismos.session')).toBe('existing-test-session');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('refuses a missing returning handle and never creates a session for a mutation or CSV preview', async () => {
    removePreference('merismos.session');
    localStorage.setItem('merismos.session.seen', 'true');
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    await expect(loadWorkspace('sandbox')).rejects.toThrow('missing');
    await expect(action(workspace(), 'offer-9000', 'approve', {consent: true}, 'old-request')).rejects.toThrow('No action was sent');
    await expect(previewCsv(workspace(), 'csv', new AbortController().signal)).rejects.toThrow('No action was sent');
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('refuses transplanting a loaded snapshot when another tab changes the session', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(workspace()))); vi.stubGlobal('fetch', fetcher);
    const snapshot = await loadWorkspace('sandbox');
    localStorage.setItem('merismos.session', 'different-session');
    await expect(action(snapshot, 'offer-9000', 'approve', {consent: true}, 'request')).rejects.toThrow('session changed');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('switches only after a replacement is readable and retains the previous handle', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({session: 'new-session'})))
      .mockResolvedValueOnce(new Response(JSON.stringify(workspace())));
    vi.stubGlobal('fetch', fetcher);
    const next = await startIsolatedWorkspace();
    expect(next.mode).toBe('sandbox');
    expect(localStorage.getItem('merismos.session')).toBe('new-session');
    expect(localStorage.getItem('merismos.retained-session.existing-test-session')).toBe('existing-test-session');
    expect(fetcher.mock.calls.map(call => call[0])).toEqual(['/api/sessions', '/api/workspace?mode=sandbox']);
    expect(fetcher.mock.calls[1][1].headers['X-Merismos-Session']).toBe('new-session');
    expect(history.state.merismosSandboxVisited).toBe(true);
  });
  it.each(['creation', 'read'])('a failed replacement %s preserves the previous session', async stage => {
    const fetcher = vi.fn();
    if (stage === 'read') fetcher.mockResolvedValueOnce(new Response(JSON.stringify({session: 'unreadable-new-session'})));
    fetcher.mockRejectedValueOnce(new Error('Connection lost')); vi.stubGlobal('fetch', fetcher);
    await expect(startIsolatedWorkspace()).rejects.toThrow('Connection lost');
    expect(localStorage.getItem('merismos.session')).toBe('existing-test-session');
  });
  it.each(['read', 'restart', 'action', 'creation'])('a superseded async %s response cannot select the previous session', async kind => {
    let finish!: (value: Response) => void;
    const fetcher = vi.fn();
    if (kind === 'restart') fetcher.mockResolvedValueOnce(new Response(JSON.stringify({session: 'candidate'})));
    if (kind === 'creation') removePreference('merismos.session');
    fetcher.mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve; }));
    vi.stubGlobal('fetch', fetcher);
    const pending = kind === 'read' ? loadWorkspace('sandbox') : kind === 'restart' ? startIsolatedWorkspace() : kind === 'creation' ? session() : action(workspace(), 'offer-9000', 'approve', {consent: true}, 'once');
    const rejected = expect(pending).rejects.toBeInstanceOf(SessionError);
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
    localStorage.setItem('merismos.session', 'selected-by-another-tab');
    finish(new Response(JSON.stringify(kind === 'creation' ? {session: 'late'} : workspace())));
    await rejected;
    expect(localStorage.getItem('merismos.session')).toBe('selected-by-another-tab');
    expect(fetcher).toHaveBeenCalledTimes(kind === 'restart' ? 2 : 1);
  });
});
