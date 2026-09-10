import { test, expect } from '@playwright/test';

// Source-only proof-display fixtures. Never included in public AWS journey totals.
const sha = '1'.repeat(40);
function receipt() {
  return {
    schema_version: 1, application: 'merismos', environment: 'live_aws', frontend_commit: sha,
    backend_commit: 'unavailable',
    backend_basis: 'Unavailable: /identity attempts Secrets Manager reads and S3 PutObject; no harmless deployed build-identity endpoint exists in the inspected source. No backend probe or SHA parity is claimed.',
    run_id: '123', run_attempt: '2', run_url: 'https://github.com/upgradedev/merismos-aws/actions/runs/123/attempts/2',
    observed_at: new Date(Date.now() - 1000).toISOString().replace(/\.\d{3}Z$/, 'Z'),
    preflight: 'SUCCESS', journeys: 'SUCCESS', postflight: 'SUCCESS',
    junit: { total: 24, passed: 24, failed: 0, skipped: 0 }, human_uat: 'NOT_RUN', mode: 'synthetic_scripted',
    limits: 'Synthetic scripted-planner/1.0.0 through real Strands and AWS HTTP persistence. Product journeys only; proof-display fixtures and post-publication proof checks are counted separately. No Bedrock model calls, real food rescue, authenticated live-coordinator publication (ME18), or human UAT.',
    workflow_status: 'NOT_ASSERTED',
  };
}

for (const scenario of ['missing', 'malformed', 'stale', 'mismatch', 'refused', 'below-floor', 'immutable-mismatch', 'unreachable', 'root-mismatch', 'root-missing', 'root-changed', 'valid', 'known-backend', 'backend-changed', 'backend-malformed'] as const) {
  test(`proof display fixture: ${scenario}`, async ({ page }) => {
    const proof = receipt();
    const hasBackend = ['known-backend', 'backend-changed', 'backend-malformed'].includes(scenario);
    if (hasBackend) {
      proof.schema_version = 2;
      proof.backend_commit = '2'.repeat(40);
      proof.backend_basis = 'Packaged backend commit observed via GET /api/version before and after the journeys; identifies the answering backend only, not every fleet function or frontend parity.';
      await page.route('**/api/version', route => route.fulfill({ json: {
        schema_version: 1, application: 'merismos', status: 'known', source: 'ci_package',
        commit: scenario === 'backend-malformed' ? 'fake' : scenario === 'backend-changed' ? sha : proof.backend_commit,
      } }));
    }
    if (scenario === 'stale') proof.observed_at = '2000-01-01T00:00:00Z';
    if (scenario === 'mismatch') proof.frontend_commit = '2'.repeat(40);
    if (scenario === 'refused') proof.postflight = 'FAILURE';
    if (scenario === 'below-floor') proof.junit = { total: 23, passed: 23, failed: 0, skipped: 0 };
    await page.route('**/release.json', route => route.fulfill({ json: { commit: sha } }));
    let rootReads = 0;
    await page.route('**/', route => {
      rootReads += 1;
      const rootSha = scenario === 'root-mismatch' || (scenario === 'root-changed' && rootReads > 1) ? '2'.repeat(40) : sha;
      const marker = scenario === 'root-missing' ? '' : `<meta name="application-commit" content="${rootSha}">`;
      return route.fulfill({ contentType: 'text/html', body: `<html><head>${marker}</head></html>` });
    });
    await page.route('**/acceptance.json', route => {
      if (scenario === 'missing') return route.fulfill({ status: 404, body: 'missing' });
      if (scenario === 'malformed') return route.fulfill({ contentType: 'text/html', body: '<html>not a receipt</html>' });
      return route.fulfill({ json: proof });
    });
    await page.route('**/acceptance/runs/*.json', route => {
      if (scenario === 'unreachable') return route.abort();
      return route.fulfill({ json: scenario === 'immutable-mismatch' ? { ...proof, run_attempt: '3' } : proof });
    });
    await page.goto('/acceptance.html');
    await expect(page.getByRole('heading', { name: 'Automated acceptance', exact: true })).toBeVisible();
    const state = ['valid', 'known-backend'].includes(scenario) ? 'PASS' : scenario === 'missing' ? 'PENDING' : ['stale', 'mismatch', 'backend-changed'].includes(scenario) ? 'HISTORICAL' : 'UNKNOWN';
    await expect(page.locator('#status')).toHaveAttribute('data-state', state);
    await expect(page.locator('#reason')).not.toHaveText('No current pass is asserted until matching proof has been read.');
    await expect(page.locator('#release')).toHaveText(sha);
    if (state === 'PASS') {
      await expect(page.locator('#total')).toHaveText('24');
      await expect(page.locator('#failed')).toHaveText('0');
      await expect(page.locator('#skipped')).toHaveText('0');
      await expect(page.locator('#backend')).toHaveText(proof.backend_commit);
      await expect(page.locator('#root-release')).toHaveText(sha);
      await expect(page.locator('#receipt-link')).toHaveAttribute('href', '/acceptance/runs/123-2.json');
    } else {
      await expect(page.locator('#status')).not.toContainText('PASS');
    }
    await expect(page.locator('#limits-heading').locator('..')).toContainText('Human UAT: NOT_RUN');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`acceptance-${scenario}.png`), fullPage: true });
  });
}
