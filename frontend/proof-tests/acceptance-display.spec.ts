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
    junit: { total: 2, passed: 2, failed: 0, skipped: 0 }, human_uat: 'NOT_RUN', mode: 'synthetic_scripted',
    limits: 'Synthetic scripted-planner/1.0.0 through real Strands and AWS HTTP persistence. Product journeys only; proof-display fixtures and post-publication proof checks are counted separately. No Bedrock model calls, real food rescue, authenticated live-coordinator publication (ME18), or human UAT.',
    workflow_status: 'NOT_ASSERTED',
  };
}

for (const scenario of ['missing', 'malformed', 'stale', 'mismatch', 'refused', 'immutable-mismatch', 'unreachable', 'valid'] as const) {
  test(`proof display fixture: ${scenario}`, async ({ page }) => {
    const proof = receipt();
    if (scenario === 'stale') proof.observed_at = '2000-01-01T00:00:00Z';
    if (scenario === 'mismatch') proof.frontend_commit = '2'.repeat(40);
    if (scenario === 'refused') proof.postflight = 'FAILURE';
    await page.route('**/release.json', route => route.fulfill({ json: { commit: sha } }));
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
    const state = scenario === 'valid' ? 'PASS' : scenario === 'missing' ? 'PENDING' : ['stale', 'mismatch'].includes(scenario) ? 'HISTORICAL' : 'UNKNOWN';
    await expect(page.locator('#status')).toHaveAttribute('data-state', state);
    await expect(page.locator('#reason')).not.toHaveText('No current pass is asserted until matching proof has been read.');
    await expect(page.locator('#release')).toHaveText(sha);
    if (scenario === 'valid') {
      await expect(page.locator('#total')).toHaveText('2');
      await expect(page.locator('#failed')).toHaveText('0');
      await expect(page.locator('#skipped')).toHaveText('0');
      await expect(page.locator('#backend')).toHaveText('unavailable');
      await expect(page.locator('#receipt-link')).toHaveAttribute('href', '/acceptance/runs/123-2.json');
    } else {
      await expect(page.locator('#status')).not.toContainText('PASS');
    }
    await expect(page.locator('#limits-heading').locator('..')).toContainText('Human UAT: NOT_RUN');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`acceptance-${scenario}.png`), fullPage: true });
  });
}
