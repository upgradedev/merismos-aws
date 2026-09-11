import { expect, test } from '@playwright/test';
import { requestCorrelation } from '../src/requestCorrelation';

test('real HTTP responses correlate individually, without accepting caller identity or altering state', async ({request}, info) => {
  const forged = 'caller-supplied-not-lambda-identity';
  const headers = {'x-merismos-request-id': forged, 'x-merismos-lambda-request-id': forged};
  const responses = [];
  const version = await request.get('/api/version', {headers});
  expect(version.status()).toBe(200);
  responses.push(version);
  const session = await request.post('/api/sessions', {headers, data: {}});
  expect(session.status()).toBe(201);
  responses.push(session);
  const sessionHeaders = {...headers, 'x-merismos-session': (await session.json()).session};
  const before = await request.get('/api/workspace?mode=sandbox', {headers: sessionHeaders});
  expect(before.status()).toBe(200);
  responses.push(before);
  const refused = await request.get('/api/workspace?mode=sandbox', {headers});
  expect(refused.status()).toBe(401);
  responses.push(refused);
  const after = await request.get('/api/workspace?mode=sandbox', {headers: sessionHeaders});
  expect(after.status()).toBe(200);
  expect(await after.json()).toEqual(await before.json());
  responses.push(after);
  const observed = responses.map(response => ({status: response.status(), ...requestCorrelation(response.headers())}));
  expect(new Set(observed.map(row => row.request_id)).size).toBe(5);
  for (const row of observed) {
    expect(row.request_id).toMatch(/^[a-f0-9-]{36}$/);
    expect(row.request_id).not.toBe(forged);
    expect(row.lambda_request_id).not.toBe(forged);
    if (process.env.MERISMOS_UI_URL) {
      expect(row.mode).toBe('lambda-context');
      expect(row.lambda_request_id).toMatch(/^[A-Za-z0-9-]{16,80}$/);
    } else {
      expect(row.mode).toBe('no-lambda-context');
      expect(row.lambda_request_id).toBeNull();
    }
  }
  await info.attach('request-correlation.json', {body: JSON.stringify({scope: process.env.MERISMOS_UI_URL ? 'HTTP_RESPONSE_CONTEXT_ONLY' : 'SOURCE_ONLY_NO_LAMBDA', responses: observed, cloud_cost: 'NOT_MEASURED'}), contentType: 'application/json'});
});
