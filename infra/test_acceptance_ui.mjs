import test from 'node:test';
import assert from 'node:assert/strict';
import { assess as assessProof, backendCommit, htmlCommit, loadProof, renderProof, validReceipt, BACKEND_BASIS, UNKNOWN_BACKEND_BASIS, KNOWN_BACKEND_BASIS, LIMITS } from '../frontend/public/acceptance.js';

const sha = '1'.repeat(40), other = '2'.repeat(40), now = Date.parse('2026-09-10T06:00:00Z');
const html = (commit = sha) => `<html><head><meta name="application-commit" content="${commit}"></head></html>`;
const assess = (release, proof, time = now, root = release?.commit) => assessProof(release, proof, time, root);
const receipt = () => ({ schema_version: 1, application: 'merismos', environment: 'live_aws',
  frontend_commit: sha, backend_commit: 'unavailable', backend_basis: BACKEND_BASIS,
  run_id: '123', run_attempt: '2', run_url: 'https://github.com/upgradedev/merismos-aws/actions/runs/123/attempts/2',
  observed_at: '2026-09-10T05:59:00Z', preflight: 'SUCCESS', journeys: 'SUCCESS', postflight: 'SUCCESS',
  junit: { total: 24, passed: 24, failed: 0, skipped: 0 }, human_uat: 'NOT_RUN', mode: 'synthetic_scripted',
  limits: LIMITS, workflow_status: 'NOT_ASSERTED' });
const response = value => ({ ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(value) });
const request = async path => path === '/' ? { ok: true, status: 200, text: async () => html() } : response(path === '/release.json' ? { commit: sha } : receipt());

test('new receipt distinguishes independently observed backend from unavailable and legacy', async () => {
  const proof = { ...receipt(), schema_version: 2, backend_commit: other, backend_basis: KNOWN_BACKEND_BASIS };
  assert.equal(validReceipt(proof), true);
  assert.equal(validReceipt({ ...proof, backend_commit: 'unavailable', backend_basis: UNKNOWN_BACKEND_BASIS }), true);
  for (const commit of [null, '', 'fake', '0'.repeat(40), true, sha + '\n']) assert.equal(validReceipt({ ...proof, backend_commit: commit }), false);
  const known = { schema_version: 1, application: 'merismos', commit: other, status: 'known', source: 'ci_package' };
  for (const value of [{ ...known, source: 'environment' }, { ...known, commit: 'fake' }, { ...known, secret: 'hidden' }, null])
    assert.throws(() => backendCommit(value));
  for (const mode of ['known', 'different', 'changed', 'missing', 'fake', 'unknown', 'wrong-mime']) {
    let reads = 0;
    const result = await loadProof(async (path, options) => {
      assert.equal(options.redirect, 'error');
      assert.notEqual(path, '/identity');
      if (path === '/api/version') {
        reads += 1;
        if (mode === 'missing') return { ok: false, status: 404 };
        if (mode === 'unknown') return response({ ...known, commit: null, status: 'unknown', source: 'unknown' });
        if (mode === 'wrong-mime') return { ...response(known), headers: { get: () => 'text/html' } };
        return response({ ...known, commit: mode === 'fake' ? 'fake' : mode === 'different' || (mode === 'changed' && reads > 1) ? sha : other });
      }
      return path.includes('acceptance') ? response(proof) : request(path);
    }, now);
    assert.equal(result.state, mode === 'known' ? 'PASS' : mode === 'different' ? 'HISTORICAL' : 'UNKNOWN', mode);
    if (mode === 'known') assert.equal(result.receipt.backend_commit, other);
  }
});

test('only a current complete receipt is PASS, with backend unavailable and no workflow-success claim', () => {
  const result = assess({ commit: sha }, receipt(), now);
  assert.equal(result.state, 'PASS');
  assert.equal(result.receipt.backend_commit, 'unavailable');
  assert.equal(result.receipt.workflow_status, 'NOT_ASSERTED');
});
test('missing, malformed, stale, future and mismatched proof do not pass', () => {
  for (const value of [undefined, {}, [], { commit: 'main' }]) assert.equal(assess(value, receipt(), now).state, 'UNKNOWN');
  assert.equal(assess({ commit: sha }, null, now).state, 'PENDING');
  for (const value of [undefined, {}, [], { ...receipt(), journeys: 'FAILURE' }, { ...receipt(), human_uat: 'PASS' },
    { ...receipt(), observed_at: '2026-02-30T06:00:00Z' }, { ...receipt(), observed_at: '2026-09-11T06:00:00Z' },
    { ...receipt(), junit: { total: 2, passed: 1, failed: 0, skipped: 1 } }]) {
    assert.equal(assess({ commit: sha }, value, now).state, 'UNKNOWN');
  }
  assert.equal(assess({ commit: other }, receipt(), now).state, 'HISTORICAL');
  assert.equal(assess({ commit: sha }, receipt(), now + 86400000).state, 'HISTORICAL');
});
test('strict schema refuses extra data, malicious links, false numbers and fabricated parity', () => {
  for (const change of [{ run_url: 'javascript:alert(1)' }, { backend_commit: sha }, { token: 'unexpected' },
    { run_id: '../../escape' }, { run_attempt: 1 }, { schema_version: true }, { environment: 'offline' },
    { limits: 'none' }, { workflow_status: 'SUCCESS' }, { backend_basis: 'matching' },
    { junit: { total: 2, passed: 2, failed: 0, skipped: 0, notes: 'private' } }]) assert.equal(validReceipt({ ...receipt(), ...change }), false);
});
test('an independent 23-case receipt fails the existing 24-journey product floor', () => {
  const small = { ...receipt(), junit: { total: 23, passed: 23, failed: 0, skipped: 0 } };
  assert.equal(validReceipt(small), false);
  assert.equal(assess({ commit: sha }, small).state, 'UNKNOWN');
  assert.equal(validReceipt({ ...receipt(), junit: { total: 25, passed: 25, failed: 0, skipped: 0 } }), true);
});
test('loader requires identical immutable receipt and checks release again', async () => {
  const paths = [];
  const result = await loadProof(async (path, options) => {
    paths.push(path); assert.equal(options.credentials, 'omit'); assert.equal(options.cache, 'no-store');
    return request(path);
  }, now);
  assert.equal(result.state, 'PASS');
  assert.deepEqual(paths, ['/release.json', '/', '/acceptance.json', '/acceptance/runs/123-2.json', '/release.json', '/']);
});
test('manifest cannot conceal a missing, conflicting, rolled-back or changing root HTML', async () => {
  assert.equal(htmlCommit(html()), sha);
  assert.equal(htmlCommit(html() + html()), undefined);
  assert.equal(assessProof({ commit: sha }, receipt(), now).state, 'UNKNOWN');
  assert.equal(assess({ commit: sha }, receipt(), now, other).state, 'UNKNOWN');
  for (const root of ['<html>missing identity</html>', html(other), html() + html()]) {
    const result = await loadProof(path => path === '/' ? { ok: true, text: async () => root } : request(path), now);
    assert.equal(result.state, 'UNKNOWN');
  }
  let reads = 0;
  const result = await loadProof(path => path === '/' ? { ok: true, text: async () => html(++reads === 1 ? sha : other) } : request(path), now);
  assert.equal(result.state, 'UNKNOWN');
});
test('missing or denied latest is pending; inaccessible or mismatched retained bytes are unknown', async () => {
  for (const status of [403, 404]) {
    const result = await loadProof(path => path === '/acceptance.json' ? { ok: false, status } : request(path), now);
    assert.equal(result.state, 'PENDING');
  }
  for (const failure of ['denied', 'different', 'malformed', 'oversize', 'network', 'changed-release']) {
    let reads = 0;
    const result = await loadProof(async path => {
      if (path === '/release.json' && ++reads === 2 && failure === 'changed-release') return response({ commit: other });
      if (path.startsWith('/acceptance/runs/')) {
        if (failure === 'denied') return { ok: false, status: 403 };
        if (failure === 'different') return response({ ...receipt(), observed_at: '2026-09-10T05:58:00Z' });
        if (failure === 'malformed') return { ok: true, text: async () => '<html>not json</html>' };
        if (failure === 'oversize') return { ok: true, text: async () => 'x'.repeat(16385) };
        if (failure === 'network') throw new Error('offline');
      }
      return request(path);
    }, now);
    assert.equal(result.state, 'UNKNOWN', failure);
    assert.equal(result.receipt, undefined);
  }
});
test('render shows validated counts and resets visible proof when subsequent fetch fails', () => {
  const nodes = new Map();
  const doc = { getElementById(id) { if (!nodes.has(id)) nodes.set(id, { dataset: {} }); return nodes.get(id); } };
  renderProof(assess({ commit: sha }, receipt(), now), doc);
  assert.equal(nodes.get('total').textContent, '24');
  assert.equal(nodes.get('backend').textContent, 'unavailable');
  assert.equal(nodes.get('status').dataset.state, 'PASS');
  assert.equal(nodes.get('receipt-link').href, '/acceptance/runs/123-2.json');
  renderProof(assess({ commit: sha }, null, now), doc);
  assert.equal(nodes.get('details').hidden, true);
  assert.equal(nodes.get('status').dataset.state, 'PENDING');
});
