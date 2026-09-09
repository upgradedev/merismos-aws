import type { Mode, Workspace } from './types';
import { readPreference, writePreference } from './storage';

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 35_000);
  const cancel = () => controller.abort();
  options.signal?.addEventListener('abort', cancel, { once: true });
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, headers: { 'Content-Type': 'application/json', ...options.headers } });
    const result = await response.json().catch(() => { throw new ApiError('The server returned an unreadable response. Try refreshing.', 502); });
    if (!response.ok) throw new ApiError(result.detail || 'The request failed. Try refreshing.', response.status);
    return result as T;
  } catch (error) {
    if (controller.signal.aborted) throw new ApiError('The request timed out or was cancelled. Refresh to inspect the outcome before retrying an action.', 408);
    throw error;
  } finally { clearTimeout(timer); options.signal?.removeEventListener('abort', cancel); }
}
let creatingSession: Promise<string> | undefined;
export async function session(): Promise<string> {
  const existing = readPreference('merismos.session');
  if (existing) return existing;
  creatingSession ??= request<{session: string}>('/api/sessions', { method: 'POST', body: '{}' }).then(result => {
    writePreference('merismos.session', result.session);
    return result.session;
  }).finally(() => { creatingSession = undefined; });
  return creatingSession;
}
export async function loadWorkspace(mode: Mode, signal?: AbortSignal): Promise<Workspace> {
  const handle = mode === 'sandbox' ? await session() : '';
  return request(`/api/workspace?mode=${mode}`, { signal, headers: { 'X-Merismos-Session': handle } });
}
export async function action(workspace: Workspace, offer: string, kind: string, payload: Record<string, unknown>, requestId: string): Promise<Workspace> {
  return request(kind === 'add' ? '/api/offers/new' : `/api/offers/${encodeURIComponent(offer)}/${kind}`, {
    method: 'POST', headers: { 'X-Merismos-Session': workspace.mode === 'sandbox' ? await session() : '' },
    body: JSON.stringify({ ...payload, mode: workspace.mode, version: workspace.version, request_id: requestId }),
  });
}
