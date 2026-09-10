import { expect, it } from 'vitest';
import { allowedRequest, latencyStats, ORIGIN, plannedAttempts, REGISTRATION, STAGES, summarize, type Identity, type Measurement } from './dispatchMeasurement';

const identity: Identity = {source_sha: 'a'.repeat(40), protocol_commit: REGISTRATION, protocol_sha256: 'b'.repeat(64), run_id: '123', run_attempt: '1'};
function fixture(): Measurement {
  return {schema: 1, scope: 'SOURCE_ONLY', identity: {...identity}, attempts: plannedAttempts().map(a => ({...a, status: 'success', elapsed_ms: 20,
    stages: STAGES.map((name, i) => ({name, start_ms: i, end_ms: i + 1, status: 'ok'})),
    requests: ['sessions', 'intake/preview', 'offers/new', 'offers/offer-4484/run', 'offers/offer-4484/approve', 'offers/offer-4484/pickup', 'offers/offer-4484/disrupt', 'offers/offer-4484/run', 'offers/offer-4484/approve', 'offers/offer-4484/pickup', 'offers/offer-4484/pickup', 'offers/offer-4484/pickup'].map((path, i) => ({id: i + 1, method: 'POST', path: `/api/${path}`, stage: 'setup', start_ms: 0, end_ms: 1, status: 200, request_body_bytes: 2, response_body_bytes: 10, error: null}))}))};
}
it('preregisters exactly20 alternating slots and never turns unrun slots into success', () => {
  expect(plannedAttempts()).toHaveLength(20);
  const result = summarize({...fixture(), attempts: plannedAttempts()}, identity);
  expect(result).toMatchObject({valid: false, planned: 20, attempted: 0, not_run: 20, successful_primary_latency: null});
});
it('reports successful-primary boundaries independently of setup/export and keeps cost unknown', () => {
  const result = summarize(fixture(), identity);
  expect(result).toMatchObject({valid: true, succeeded: 20, failed: 0, request_count: 240, request_body_bytes: 480, response_body_bytes: 2400, aws_cost: 'NOT_MEASURED'});
  expect(result.successful_primary_latency?.desktop).toEqual({n: 10, median_ms: 11, p95_ms: 11, min_ms: 11, max_ms: 11});
  expect(result.all_attempts_succeeded).toBe(true);
});
it('retains failure denominators and null response sizes without inventing zero-latency successes', () => {
  const raw = fixture(), a = raw.attempts[0]; a.status = 'failed'; a.error = 'request_failed'; a.failure_stage = 'setup'; a.stages = []; a.requests[0].end_ms = null; a.requests[0].response_body_bytes = null;
  const result = summarize(raw, identity);
  expect(result).toMatchObject({valid: true, succeeded: 19, failed: 1, attempted: 20, all_attempts_succeeded: false});
  expect(result.successful_primary_latency?.overall.n).toBe(19);
});
it.each([
  (m: Measurement) => {m.attempts.pop();},
  (m: Measurement) => {m.attempts.reverse();},
  (m: Measurement) => {m.attempts[1] = m.attempts[0];},
  (m: Measurement) => {m.attempts[0].elapsed_ms = NaN;},
  (m: Measurement) => {m.attempts[0].elapsed_ms = 60_001;},
  (m: Measurement) => {m.attempts[0].stages[1].start_ms = -1;},
  (m: Measurement) => {m.attempts[0].stages[1].end_ms = Infinity;},
  (m: Measurement) => {m.attempts[0].stages[2].start_ms = 0;},
  (m: Measurement) => {m.attempts[0].stages.pop();},
  (m: Measurement) => {m.attempts[0].stages[0].status = 'failed';},
  (m: Measurement) => {m.attempts[0].requests[0].end_ms = -1;},
  (m: Measurement) => {m.attempts[0].requests[0].request_body_bytes = .5;},
  (m: Measurement) => {m.attempts[0].requests[0].response_body_bytes = null;},
  (m: Measurement) => {m.attempts[0].requests[0].path += '?session=redacted';},
  (m: Measurement) => {m.attempts[0].requests[1].id = 1;},
  (m: Measurement) => {m.attempts[0].requests.pop();},
  (m: Measurement) => {m.attempts[0].requests[0].status = 500;},
  (m: Measurement) => {m.attempts[0].status = 'failed';},
  (m: Measurement) => {m.identity.source_sha = 'c'.repeat(40);},
  (m: Measurement) => {m.identity.protocol_sha256 = 'c'.repeat(64);},
  (m: Measurement) => {m.scope = 'AWS' as 'SOURCE_ONLY';},
])('refuses corrupted or selectively incomplete instrument data %#', mutate => {
  const raw = fixture(); mutate(raw); const result = summarize(raw, identity);
  expect(result.valid).toBe(false); expect(result.successful_primary_latency).toBeNull();
});
it.each([{source_sha: REGISTRATION}, {protocol_commit: '0'.repeat(40)}, {protocol_sha256: ''}, {run_id: ''}, {run_attempt: '0'}])('rejects an unregistered or missing identity %#', change => {
  expect(summarize(fixture(), {...identity, ...change}).valid).toBe(false);
});
it('calculates median and nearest-rank p95 without mutating or discarding samples', () => {
  const values = Array.from({length: 20}, (_, i) => 20 - i);
  expect(latencyStats(values)).toEqual({n: 20, median_ms: 10.5, p95_ms: 19, min_ms: 1, max_ms: 20});
  expect(values[0]).toBe(20); expect(latencyStats([3, 1, 2]).median_ms).toBe(2);
  expect(latencyStats([]).n).toBe(0); expect(() => latencyStats([-1])).toThrow('Invalid latency');
});
it.each(['https://example.com/api/sessions', 'http://localhost:4173/', `${ORIGIN}/identity`, `${ORIGIN}/api/workspace?mode=live`, `${ORIGIN}/api/version`, 'not a URL', 'http://user:pass@127.0.0.1:4173/'])('blocks out-of-scope GET before network: %s', url => {
  expect(allowedRequest(url, 'GET', null)).toBe(false);
});
it('only permits existing sandbox HTTP routes, never publication identities or unrelated writes', () => {
  expect(allowedRequest(ORIGIN + '/', 'GET', null)).toBe(true);
  expect(allowedRequest(ORIGIN + '/api/workspace?mode=sandbox', 'GET', null)).toBe(true);
  expect(allowedRequest(ORIGIN + '/api/sessions', 'POST', '{}')).toBe(true);
  expect(allowedRequest(ORIGIN + '/api/intake/preview', 'POST', '{"mode":"sandbox"}')).toBe(true);
  expect(allowedRequest(ORIGIN + '/api/offers/offer-4484/run', 'POST', '{"mode":"sandbox"}')).toBe(true);
  for (const [path, method, body] of [['/api/sessions', 'DELETE', '{}'], ['/api/sessions', 'POST', 'bad'], ['/api/offers/new', 'POST', '{"mode":"live"}'], ['/api/offers/offer-4471/run', 'POST', '{"mode":"sandbox"}'], ['/api/offers/new', 'POST', 'bad'], ['/api/identity', 'POST', '{}'], ['/unknown', 'POST', '{}']]) expect(allowedRequest(ORIGIN + path, method, body)).toBe(false);
});
