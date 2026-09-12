import type { Mode, Workspace } from './types';
import { readPreference, writePreference } from './storage';

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export class SessionError extends ApiError {}
const workspaceSessions = new WeakMap<Workspace, string>();
function rememberSession(handle: string) {
  writePreference('merismos.session', handle);
  writePreference('merismos.session.seen', 'true');
  writePreference('merismos.session.context', crypto.randomUUID());
  history.replaceState({ ...history.state, merismosSandboxVisited: true }, '');
}
function actionSession(workspace: Workspace): string {
  if (workspace.mode !== 'sandbox') return '';
  const handle = readPreference('merismos.session');
  if (!handle) throw new SessionError('The saved session handle is missing. No action was sent.', 401);
  const loaded = workspaceSessions.get(workspace);
  if (loaded && loaded !== handle) throw new SessionError('The browser session changed since this workspace was loaded. No action was sent.', 401);
  return handle;
}
async function readWorkspace(mode: Mode, handle: string, signal?: AbortSignal): Promise<Workspace> {
  try {
    const workspace = await request<Workspace>(`/api/workspace?mode=${mode}`, { signal, headers: { 'X-Merismos-Session': handle } });
    if (mode === 'sandbox') workspaceSessions.set(workspace, handle);
    return workspace;
  } catch (error) {
    if (mode === 'sandbox' && error instanceof ApiError && [401, 403, 404, 410].includes(error.status)) throw new SessionError(error.message, error.status);
    throw error;
  }
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 35_000);
  const cancel = () => controller.abort();
  options.signal?.addEventListener('abort', cancel, { once: true });
  if (options.signal?.aborted) controller.abort();
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
  if (readPreference('merismos.session.seen') || history.state?.merismosSandboxVisited) {
    throw new SessionError('The saved session handle is missing. The previous workspace cannot be opened without it.', 401);
  }
  creatingSession ??= request<{session: string}>('/api/sessions', { method: 'POST', body: '{}' }).then(result => {
    if (readPreference('merismos.session')) throw new SessionError('The browser session changed while connecting. The previous response was not selected.', 401);
    rememberSession(result.session);
    return result.session;
  }).finally(() => { creatingSession = undefined; });
  return creatingSession;
}
export async function loadWorkspace(mode: Mode, signal?: AbortSignal): Promise<Workspace> {
  const handle = mode === 'sandbox' ? await session() : '';
  const workspace = await readWorkspace(mode, handle, signal);
  if (mode === 'sandbox' && readPreference('merismos.session') !== handle) throw new SessionError('The browser session changed while loading. The previous response was not selected.', 401);
  return workspace;
}
// Only an explicit restart may replace a handle. Read the replacement before
// switching; a failed creation/read leaves the previous session selected.
export async function startIsolatedWorkspace(): Promise<Workspace> {
  const previous = readPreference('merismos.session');
  const result = await request<{session: string}>('/api/sessions', { method: 'POST', body: '{}' });
  const workspace = await readWorkspace('sandbox', result.session);
  if (readPreference('merismos.session') !== previous) throw new SessionError('The browser session changed during restart. The replacement was not selected.', 401);
  if (previous) writePreference(`merismos.retained-session.${previous}`, previous);
  rememberSession(result.session);
  return workspace;
}
export async function action(workspace: Workspace, offer: string, kind: string, payload: Record<string, unknown>, requestId: string): Promise<Workspace> {
  if (kind === 'import') {
    let current = workspace;
    const rows = payload.rows as number[];
    for (const [index, row] of rows.entries()) {
      try {
        current = await action(current, '', 'add', { csv: payload.csv, csv_digest: payload.csv_digest, row }, `${requestId}-${row}`);
      } catch (error) {
        throw new ApiError(`Import stopped after ${index} confirmed rows. CSV row ${row}: ${error instanceof Error ? error.message : 'Outcome unknown.'} Earlier confirmed rows remain filed. Refresh and preview again before selecting any remaining rows.`, error instanceof ApiError ? error.status : 502);
      }
    }
    return current;
  }
  const handle = actionSession(workspace);
  const next = await request<Workspace>(kind === 'add' ? '/api/offers/new' : `/api/offers/${encodeURIComponent(offer)}/${kind}`, {
    method: 'POST', headers: { 'X-Merismos-Session': handle },
    body: JSON.stringify({ ...payload, mode: workspace.mode, version: workspace.version, request_id: requestId }),
  });
  if (workspace.mode === 'sandbox' && readPreference('merismos.session') !== handle) throw new SessionError('The session changed while saving. Read the original workspace to inspect the outcome; no action was replayed.', 401);
  if (workspace.mode === 'sandbox') workspaceSessions.set(next, handle);
  return next;
}

export interface CsvPreview {
  digest: string; version: number; mode: Mode; max_bytes: number; max_rows: number;
  rows: {number: number; status: 'valid' | 'invalid' | 'duplicate'; detail: string; offer: import('./types').Offer | null}[];
}
export async function previewCsv(workspace: Workspace, csv: string, signal: AbortSignal): Promise<CsvPreview> {
  return request('/api/intake/preview', {method: 'POST', signal,
    headers: {'X-Merismos-Session': actionSession(workspace)},
    body: JSON.stringify({mode: workspace.mode, csv})});
}
