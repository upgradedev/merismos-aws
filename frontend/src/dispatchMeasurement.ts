// Source-only measurement bookkeeping. No production component imports this module.
export const REGISTRATION = '9ebbafff736ff739fd22ee9c4c845e5b709cc25a';
export const ORIGIN = 'http://127.0.0.1:4173';
export const STAGES = ['setup', 'csv_preview', 'file', 'allocate', 'approve_original', 'claim_original', 'disrupt', 'replan', 'approve_new', 'claim_new', 'schedule', 'confirm', 'copy_manifest', 'download_manifest'] as const;
export type StageName = typeof STAGES[number];
export type Identity = {source_sha: string; protocol_commit: string; protocol_sha256: string; run_id: string; run_attempt: string};
export type Stage = {name: StageName; start_ms: number; end_ms: number; status: 'ok' | 'failed'};
export type HttpSample = {id: number; method: string; path: string; stage: string; start_ms: number; end_ms: number | null; status: number | null; request_body_bytes: number; response_body_bytes: number | null; error: string | null};
export type Attempt = {ordinal: number; viewport: 'desktop' | 'mobile'; status: 'not_run' | 'running' | 'success' | 'failed'; elapsed_ms: number | null; failure_stage: string | null; error: string | null; stages: Stage[]; requests: HttpSample[]};
export type Measurement = {schema: 1; scope: 'SOURCE_ONLY'; identity: Identity; attempts: Attempt[]};

export function plannedAttempts(): Attempt[] {
  return Array.from({length: 20}, (_, i) => ({ordinal: i + 1, viewport: i % 2 === 0 ? 'desktop' : 'mobile', status: 'not_run', elapsed_ms: null, failure_stage: null, error: null, stages: [], requests: []}));
}

// A supplied remote origin, live mode or identity probe must fail before any fetch.
export function allowedRequest(address: string, method: string, body: string | null): boolean {
  try {
    const url = new URL(address);
    if (url.origin !== ORIGIN || url.username || url.password || url.pathname.includes('identity')) return false;
    if (method === 'GET') return !url.pathname.startsWith('/api/') || (url.pathname === '/api/workspace' && url.searchParams.get('mode') === 'sandbox');
    if (method !== 'POST') return false;
    if (url.pathname === '/api/sessions') return body === '{}';
    if (url.pathname !== '/api/intake/preview' && !/^\/api\/offers\/(?:new|offer-\d+\/(?:run|approve|pickup|disrupt))$/.test(url.pathname)) return false;
    return JSON.parse(body || '{}').mode === 'sandbox' && !url.pathname.includes('offer-4471/');
  } catch { return false; }
}

const nonnegative = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n >= 0;
const byteCount = (n: unknown) => nonnegative(n) && Number.isInteger(n);
export function latencyStats(values: number[]) {
  if (!values.length) return {n: 0, median_ms: null, p95_ms: null, min_ms: null, max_ms: null};
  if (!values.every(nonnegative)) throw new Error('Invalid latency');
  const sorted = [...values].sort((a, b) => a - b), n = sorted.length;
  return {n, median_ms: n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2,
    p95_ms: sorted[Math.ceil(n * .95) - 1], min_ms: sorted[0], max_ms: sorted[n - 1]};
}

export function summarize(measurement: Measurement, expected: Identity) {
  const issues: string[] = [];
  if (measurement.schema !== 1 || measurement.scope !== 'SOURCE_ONLY') issues.push('Wrong evidence scope/schema');
  if (!/^[a-f0-9]{40}$/.test(expected.source_sha) || expected.source_sha === REGISTRATION || expected.protocol_commit !== REGISTRATION || !/^[a-f0-9]{64}$/.test(expected.protocol_sha256) || !/^\d+$/.test(expected.run_id) || !/^[1-9]\d*$/.test(expected.run_attempt)) issues.push('Invalid expected source identity');
  if (!measurement.identity || (Object.keys(expected) as (keyof Identity)[]).some(k => measurement.identity[k] !== expected[k])) issues.push('Source/protocol/run identity mismatch');
  const attempts = Array.isArray(measurement.attempts) ? measurement.attempts : [];
  if (attempts.length !== 20) issues.push('Expected exactly 20 attempt slots');
  let succeeded = 0, failed = 0, interrupted = 0, notRun = 0;
  const times: Record<string, number[]> = {desktop: [], mobile: [], overall: []};
  for (const [i, attempt] of attempts.entries()) {
    const label = `Attempt ${i + 1}`;
    if (attempt.ordinal !== i + 1 || attempt.viewport !== (i % 2 === 0 ? 'desktop' : 'mobile')) issues.push(`${label}: duplicate, missing or reordered identity`);
    if (attempt.status === 'success') succeeded++;
    else if (attempt.status === 'failed') failed++;
    else { if (attempt.status === 'running') interrupted++; else notRun++; issues.push(`${label}: not completed`); continue; }
    if (!nonnegative(attempt.elapsed_ms) || attempt.elapsed_ms > 60_000) issues.push(`${label}: invalid elapsed/budget`);
    const stages = attempt.stages;
    if (!Array.isArray(stages) || !Array.isArray(attempt.requests)) { issues.push(`${label}: missing instrumentation`); continue; }
    if (attempt.status === 'success' && (stages.length !== STAGES.length || attempt.failure_stage !== null || attempt.error !== null)) issues.push(`${label}: incomplete success`);
    if (attempt.status === 'failed' && (!attempt.failure_stage || !attempt.error)) issues.push(`${label}: missing failure evidence`);
    let previous = 0;
    for (const [j, stage] of stages.entries()) {
      if (stage.name !== STAGES[j] || !nonnegative(stage.start_ms) || !nonnegative(stage.end_ms) || stage.start_ms < previous || stage.end_ms < stage.start_ms || stage.end_ms > (attempt.elapsed_ms ?? -1) || !['ok', 'failed'].includes(stage.status) || (attempt.status === 'success' && stage.status !== 'ok')) issues.push(`${label}: invalid stage ordering/clock/status`);
      previous = stage.end_ms;
    }
    const ids = new Set<number>();
    for (const r of attempt.requests) {
      if (!Number.isInteger(r.id) || r.id < 1 || ids.has(r.id)) issues.push(`${label}: duplicate/invalid request identity`);
      ids.add(r.id);
      if (!nonnegative(r.start_ms) || (r.end_ms !== null && (!nonnegative(r.end_ms) || r.end_ms < r.start_ms || r.end_ms > (attempt.elapsed_ms ?? -1))) || !byteCount(r.request_body_bytes) || (r.response_body_bytes !== null && !byteCount(r.response_body_bytes))) issues.push(`${label}: invalid request measurement`);
      if (!r.path.startsWith('/') || r.path.includes('?') || !STAGES.includes(r.stage as StageName) || !['GET', 'POST'].includes(r.method)) issues.push(`${label}: invalid request metadata`);
      if (attempt.status === 'success' && (r.error !== null || r.end_ms === null || r.response_body_bytes === null || r.status === null || r.status < 200 || r.status >= 400)) issues.push(`${label}: incomplete/failed request in success`);
    }
    if (attempt.status === 'success') {
      // At least one real session and every primary backend transition are required.
      const posts = attempt.requests.filter(r => r.method === 'POST');
      for (const [suffix, count] of [['/sessions', 1], ['/preview', 1], ['/new', 1], ['/run', 2], ['/approve', 2], ['/pickup', 4], ['/disrupt', 1]] as const) {
        if (posts.filter(r => r.path.endsWith(suffix)).length !== count) issues.push(`${label}: unexpected ${suffix} request count`);
      }
      const start = stages.find(s => s.name === 'csv_preview'), end = stages.find(s => s.name === 'confirm');
      if (start && end && nonnegative(end.end_ms - start.start_ms)) {
        times.overall.push(end.end_ms - start.start_ms);
        if (times[attempt.viewport]) times[attempt.viewport].push(end.end_ms - start.start_ms);
      }
    }
  }
  return {valid: issues.length === 0, issues, planned: 20, attempted: succeeded + failed + interrupted, succeeded, failed, interrupted, not_run: notRun,
    all_attempts_succeeded: issues.length === 0 && succeeded === 20,
    successful_primary_latency: issues.length ? null : Object.fromEntries(Object.entries(times).map(([view, values]) => [view, latencyStats(values)])),
    request_count: attempts.reduce((n, a) => n + (a.requests?.length || 0), 0),
    request_body_bytes: attempts.reduce((n, a) => n + (a.requests || []).reduce((v, r) => v + (byteCount(r.request_body_bytes) ? r.request_body_bytes : 0), 0), 0),
    response_body_bytes: attempts.reduce((n, a) => n + (a.requests || []).reduce((v, r) => v + (byteCount(r.response_body_bytes) ? r.response_body_bytes! : 0), 0), 0),
    byte_basis: 'Application body bytes only; not wire bytes or billing units. Unknown response sizes stay null in raw samples.',
    model_network: 'PROHIBITED_BY_SOURCE_HARNESS', aws_cost: 'NOT_MEASURED', model_cost: 'NOT_MEASURED', human_time_saved: 'NOT_MEASURED'};
}
