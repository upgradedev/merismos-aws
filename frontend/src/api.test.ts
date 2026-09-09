import { describe, expect, it, vi } from 'vitest';
import { action, ApiError, loadWorkspace, request, session } from './api';
import { removePreference } from './storage';
import { workspace } from './test/fixtures';

describe('HTTP and session boundary', () => {
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
});
