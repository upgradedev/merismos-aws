const SHA = /^[0-9a-f]{40}$/;
const NUMBER = /^[1-9][0-9]*$/;
const REPO = 'https://github.com/upgradedev/merismos-aws';
export const BACKEND_BASIS = 'Unavailable: /identity attempts Secrets Manager reads and S3 PutObject; no harmless deployed build-identity endpoint exists in the inspected source. No backend probe or SHA parity is claimed.';
export const UNKNOWN_BACKEND_BASIS = 'Backend version unavailable from GET /api/version; no backend commit or fleet parity is claimed.';
export const KNOWN_BACKEND_BASIS = 'Packaged backend commit observed via GET /api/version before and after the journeys; identifies the answering backend only, not every fleet function or frontend parity.';
export const LIMITS = 'Synthetic scripted-planner/1.0.0 through real Strands and AWS HTTP persistence. Product journeys only; proof-display fixtures and post-publication proof checks are counted separately. No Bedrock model calls, real food rescue, authenticated live-coordinator publication (ME18), or human UAT.';
const FIELDS = ['schema_version', 'application', 'environment', 'frontend_commit', 'backend_commit', 'backend_basis', 'run_id', 'run_attempt', 'run_url', 'observed_at', 'preflight', 'journeys', 'postflight', 'junit', 'human_uat', 'mode', 'limits', 'workflow_status'];
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const keys = (value, expected) => object(value) && Object.keys(value).sort().join('|') === [...expected].sort().join('|');
const sorted = value => JSON.stringify(value, FIELDS.concat(['total', 'passed', 'failed', 'skipped']).sort());
const knownCommit = value => typeof value === 'string' && value.length === 40 && SHA.test(value) && value !== '0'.repeat(40);

export function backendCommit(value) {
  if (!keys(value, ['schema_version', 'application', 'commit', 'status', 'source'])
    || value.schema_version !== 1 || value.application !== 'merismos') throw new Error('backend schema');
  if (value.commit === null && value.status === 'unknown' && value.source === 'unknown') return null;
  if (!knownCommit(value.commit) || value.status !== 'known' || value.source !== 'ci_package') throw new Error('backend identity');
  return value.commit;
}

export function validReceipt(p) {
  return keys(p, FIELDS) && [1, 2].includes(p.schema_version) && p.application === 'merismos' && p.environment === 'live_aws'
    && typeof p.frontend_commit === 'string' && SHA.test(p.frontend_commit)
    && (p.schema_version === 1 ? p.backend_commit === 'unavailable' && p.backend_basis === BACKEND_BASIS
      : (p.backend_commit === 'unavailable' && p.backend_basis === UNKNOWN_BACKEND_BASIS)
        || (knownCommit(p.backend_commit) && p.backend_basis === KNOWN_BACKEND_BASIS))
    && ['run_id', 'run_attempt'].every(key => typeof p[key] === 'string' && NUMBER.test(p[key]))
    && p.run_url === `${REPO}/actions/runs/${p.run_id}/attempts/${p.run_attempt}`
    && ['preflight', 'journeys', 'postflight'].every(key => p[key] === 'SUCCESS')
    && keys(p.junit, ['total', 'passed', 'failed', 'skipped'])
    && Object.values(p.junit).every(n => Number.isSafeInteger(n) && n >= 0)
    && p.junit.total >= 24 && p.junit.total === p.junit.passed && p.junit.failed === 0 && p.junit.skipped === 0
    && p.human_uat === 'NOT_RUN' && p.mode === 'synthetic_scripted' && p.limits === LIMITS
    && p.workflow_status === 'NOT_ASSERTED' && typeof p.observed_at === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(p.observed_at)
    && Number.isFinite(Date.parse(p.observed_at))
    && new Date(p.observed_at).toISOString().replace('.000Z', 'Z') === p.observed_at;
}

export function htmlCommit(body) {
  const matches = [...body.matchAll(/<meta name="application-commit" content="([0-9a-f]{40})">/g)];
  return matches.length === 1 ? matches[0][1] : undefined;
}

export function assess(release, receipt, now = Date.now(), rootCommit) {
  if (!object(release) || typeof release.commit !== 'string' || !SHA.test(release.commit))
    return { state: 'UNKNOWN', reason: 'Deployed release identity is missing or malformed.' };
  if (!rootCommit || rootCommit !== release.commit)
    return { state: 'UNKNOWN', reason: 'Served root HTML identity is missing or disagrees with the manifest. No current pass is asserted.', release: release.commit, html_commit: rootCommit };
  if (receipt === null) return { state: 'PENDING', reason: 'No receipt is published for inspection. Acceptance is pending or unavailable.', release: release.commit, html_commit: rootCommit };
  if (!validReceipt(receipt)) return { state: 'UNKNOWN', reason: 'Receipt is malformed, incomplete or refused. No current pass is asserted.', release: release.commit };
  const age = now - Date.parse(receipt.observed_at);
  if (age < 0) return { state: 'UNKNOWN', reason: 'Receipt observation is in the future.', release: release.commit };
  const base = { release: release.commit, html_commit: rootCommit, receipt };
  if (receipt.frontend_commit !== release.commit) return { ...base, state: 'HISTORICAL', reason: 'The recorded frontend differs from the served release. Current acceptance is pending.' };
  if (age > 86_400_000) return { ...base, state: 'HISTORICAL', reason: 'This observation is older than 24 hours. Current acceptance needs a new run.' };
  return { ...base, state: 'PASS', reason: `Matching frontend: scripted AWS browser journeys passed. ${knownCommit(receipt.backend_commit) ? 'The answering backend commit was observed separately; fleet parity is not asserted.' : 'Backend identity remains unavailable;'} overall workflow conclusion is not asserted.` };
}

export async function loadProof(request = fetch, now = Date.now()) {
  let release;
  async function read(path, missing = false, raw = false) {
    const response = await request(path, { cache: 'no-store', credentials: 'omit', redirect: 'error' });
    if (missing && [403, 404].includes(response.status)) return null;
    if (!response.ok) throw new Error('unavailable');
    const text = await response.text();
    if (text.length > (raw || path === '/release.json' ? 2_000_000 : 16_384)) throw new Error('oversized');
    return raw ? text : JSON.parse(text);
  }
  try {
    release = await read('/release.json');
    const rootCommit = htmlCommit(await read('/', false, true));
    const receipt = await read('/acceptance.json', true);
    const result = assess(release, receipt, now, rootCommit);
    if (result.receipt) {
      const retained = await read(`/acceptance/runs/${receipt.run_id}-${receipt.run_attempt}.json`);
      if (!validReceipt(retained) || sorted(retained) !== sorted(receipt)) throw new Error('immutable mismatch');
    }
    let backend;
    if (result.receipt && knownCommit(receipt.backend_commit)) {
      backend = backendCommit(await read('/api/version'));
      if (backend !== receipt.backend_commit) return { ...result, state: 'HISTORICAL', reason: 'The answering backend differs from the recorded version. Current acceptance needs a new run.' };
    }
    const after = await read('/release.json');
    const afterRoot = htmlCommit(await read('/', false, true));
    if (!object(after) || after.commit !== release.commit || afterRoot !== rootCommit) throw new Error('release changed');
    if (backend && backendCommit(await read('/api/version')) !== backend) throw new Error('backend changed');
    return result;
  } catch {
    return { state: 'UNKNOWN', reason: 'Release or retained proof is unreachable, malformed, mismatched or changed during this check. No current pass is asserted.',
      release: object(release) && SHA.test(release.commit) ? release.commit : undefined };
  }
}

export function renderProof(result, doc = document) {
  const put = (id, value) => { doc.getElementById(id).textContent = String(value); };
  put('status', `${result.state} · ${result.state === 'PASS' ? 'Scripted AWS journeys' : 'Current acceptance unverified'}`);
  doc.getElementById('status').dataset.state = result.state;
  put('reason', result.reason);
  put('release', result.release || 'Unknown');
  put('root-release', result.html_commit || 'Unknown');
  const p = result.receipt;
  doc.getElementById('details').hidden = !p;
  if (!p) return;
  put('recorded', p.frontend_commit); put('backend', p.backend_commit); put('basis', p.backend_basis);
  put('observed', p.observed_at); put('run', `${p.run_id} / ${p.run_attempt}`);
  put('phases', `${p.preflight} / ${p.journeys} / ${p.postflight}`);
  for (const key of ['total', 'passed', 'failed', 'skipped']) put(key, p.junit[key]);
  put('limits', p.limits);
  doc.getElementById('receipt-link').href = `/acceptance/runs/${p.run_id}-${p.run_attempt}.json`;
  doc.getElementById('run-link').href = p.run_url;
}

if (typeof document !== 'undefined' && document.getElementById('status')) {
  renderProof(await loadProof());
}
