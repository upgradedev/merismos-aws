import { test, expect } from '@playwright/test';

test('actual served public proof reports its observed state without runtime mutations', async ({ page, request }) => {
  const mutations: string[] = [];
  page.on('request', req => { if (!['GET', 'HEAD'].includes(req.method())) mutations.push(req.url()); });
  const response = await page.goto('/acceptance.html');
  expect(response?.status()).toBe(200);
  await expect(page.getByRole('heading', { name: 'Automated acceptance', exact: true })).toBeVisible();
  await expect(page.locator('#reason')).not.toHaveText('No current pass is asserted until matching proof has been read.');
  await expect(page.locator('#status')).toHaveAttribute('data-state', /^(PASS|PENDING|UNKNOWN|HISTORICAL)$/);
  if (process.env.EXPECTED_PROOF_RUN) {
    // Dedicated post-publication job: read real public JSON and actual rendered pixels.
    await expect(page.locator('#status')).toHaveAttribute('data-state', 'PASS');
    await expect(page.locator('#release')).toHaveText(process.env.EXPECTED_RELEASE!);
    await expect(page.locator('#root-release')).toHaveText(process.env.EXPECTED_RELEASE!);
    await expect(page.locator('#recorded')).toHaveText(process.env.EXPECTED_RELEASE!);
    await expect(page.locator('#run')).toHaveText(`${process.env.EXPECTED_PROOF_RUN} / ${process.env.EXPECTED_PROOF_ATTEMPT}`);
    const latest = await request.get('/acceptance.json');
    expect(latest.status()).toBe(200);
    const proof = await latest.json();
    const retained = await request.get(`/acceptance/runs/${proof.run_id}-${proof.run_attempt}.json`);
    expect(retained.status()).toBe(200);
    expect(await retained.json()).toEqual(proof);
    await expect(page.locator('#total')).toHaveText(String(proof.junit.total));
    expect(proof.junit.total).toBeGreaterThanOrEqual(24);
    expect(proof.junit.passed).toBe(proof.junit.total);
    expect(proof.junit.failed).toBe(0);
    expect(proof.junit.skipped).toBe(0);
    expect(proof.human_uat).toBe('NOT_RUN');
    expect(proof.workflow_status).toBe('NOT_ASSERTED');
  } else if (!process.env.MERISMOS_UI_URL) {
    // Offline preview has no deployed release manifest and cannot claim a live pass.
    await expect(page.locator('#status')).toHaveAttribute('data-state', 'UNKNOWN');
  }
  expect(mutations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('actual-public-proof.png'), fullPage: true });
});
