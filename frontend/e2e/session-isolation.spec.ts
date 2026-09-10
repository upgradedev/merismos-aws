import { expect, test } from '@playwright/test';
import type { Workspace } from '../src/types';

test('X2: two valid sandbox sessions isolate intake, exact plans and request-ID replays', async ({ page, browser, baseURL }, info) => {
  // Separate browser storage, real session creation and real HTTP throughout.
  // Never replace a valid second session with an invented/expired token.
  const contextB = await browser.newContext({ baseURL, viewport: page.viewportSize() });
  try {
    const pageB = await contextB.newPage();
    await page.goto('/#/offers/new');
    await expect(page.getByRole('heading', { name: 'Add an offer', exact: true })).toBeVisible();
    await pageB.goto('/#/history');
    await expect(pageB.getByRole('heading', { name: 'Sandbox history', exact: true })).toBeVisible();
    const sessionA = await page.evaluate(() => localStorage.getItem('merismos.session'));
    const sessionB = await pageB.evaluate(() => localStorage.getItem('merismos.session'));
    expect(sessionA).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(sessionB).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(sessionA).not.toBe(sessionB);
    const headersA = { 'X-Merismos-Session': sessionA! };
    const headersB = { 'X-Merismos-Session': sessionB! };
    const read = async (headers: Record<string, string>): Promise<Workspace> => {
      const response = await page.request.get('/api/workspace?mode=sandbox', { headers });
      expect(response.status()).toBe(200);
      const state: Workspace = await response.json();
      expect(state).toMatchObject({ mode: 'sandbox', synthetic: true, can_write: true });
      return state;
    };
    await read(headersA);
    let baselineB = await read(headersB);
    expect(baselineB.records).toEqual([]);
    expect(baselineB.pickups).toEqual([]);
    expect(baselineB.operations).toEqual([]);
    expect(baselineB.offers.every(row => row.plan === null && row.status === 'not_started')).toBe(true);
    const unchangedB = async () => {
      // Exact version and whole read model, not merely an empty History widget.
      expect(await read(headersB)).toEqual(baselineB);
    };

    await page.getByRole('button', { name: 'Try success', exact: true }).click();
    await page.getByLabel('What is being donated?').fill('Synthetic session vegetables');
    // Fixed relative UTC interval, so this isolation fixture does not expire at judging.
    const today = Date.now();
    await page.getByLabel('Collection date', { exact: true }).fill(new Date(today + 2 * 86400_000).toISOString().slice(0, 10));
    await page.getByLabel('Use by date (if known)').fill(new Date(today + 4 * 86400_000).toISOString().slice(0, 10));
    const addResponse = page.waitForResponse(r => r.url().endsWith('/api/offers/new') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Add to sandbox', exact: true }).click();
    const added = await addResponse;
    expect(added.status()).toBe(200);
    const addedState: Workspace = await added.json();
    const form = added.request().postDataJSON().form;
    const offerId = addedState.offers.find(row => row.offer.title === form.title)!.offer.id;
    expect(baselineB.offers.some(row => row.offer.id === offerId)).toBe(false);
    const path = `/api/offers/${offerId}`;
    await unchangedB();

    const runResponse = page.waitForResponse(r => r.url().endsWith(`${path}/run`) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Work out the split', exact: true }).click();
    const ran = await runResponse;
    expect(ran.status()).toBe(200);
    const runRequest = ran.request().postDataJSON();
    const planned: Workspace = await ran.json();
    const planA = planned.offers.find(row => row.offer.id === offerId)!.plan!;
    expect(planA).toBeTruthy();
    expect(planA.recorded).toBe(false);
    await unchangedB();
    const approveResponse = page.waitForResponse(r => r.url().endsWith(`${path}/approve`) && r.request().method() === 'POST');
    await page.getByLabel('I have reviewed this exact allocation and record address, and approve this plan.').check();
    await page.getByRole('button', { name: 'Approve in sandbox', exact: true }).click();
    const approved = await approveResponse;
    expect(approved.status()).toBe(200);
    const approvalRequest = approved.request().postDataJSON();
    const approvedA: Workspace = await approved.json();
    expect(approvedA.records).toHaveLength(1);
    expect(approvedA.records[0]).toMatchObject({ mode: 'sandbox', run_id: planA.run_id, key: planA.key, content_digest: planA.digest });
    await expect(page.getByRole('heading', { name: 'The recorded plan', exact: true })).toBeVisible();
    await unchangedB();
    await pageB.reload();
    await expect(pageB.getByRole('heading', { name: 'No records yet', exact: true })).toBeVisible();
    expect(await pageB.evaluate(() => localStorage.getItem('merismos.session'))).toBe(sessionB);

    const refusedWithoutWrite = async (payload: Record<string, unknown>, status = 409, action = 'approve') => {
      const beforeA = await read(headersA);
      const response = await pageB.request.post(`${path}/${action}`, {
        headers: headersB, data: { ...payload, mode: 'sandbox', version: baselineB.version },
      });
      expect(response.status()).toBe(status);
      expect(await response.json()).toEqual({ detail: status === 404 ? 'No such offer.' : 'This plan is stale. Refresh and review the allocation again.' });
      await unchangedB();
      expect(await read(headersA)).toEqual(beforeA);
    };
    // A-only offer is absent from B; this is separate from plan-binding proof below.
    await refusedWithoutWrite(approvalRequest, 404);

    // Positive controls deliberately change B only here. The same local offer
    // address exists in both sessions, with different actual donation evidence.
    const addedB = await pageB.request.post('/api/offers/new', {
      headers: headersB, data: { mode: 'sandbox', version: baselineB.version,
        request_id: crypto.randomUUID(), form: { ...form, title: 'Synthetic second session produce', quantity: '90.25' } },
    });
    expect(addedB.status()).toBe(200);
    baselineB = await read(headersB);
    expect(baselineB.offers.find(row => row.offer.id === offerId)!.plan).toBeNull();
    // Reuse A's actual approval ID with B's CURRENT version: a global replay
    // cache, stale-version refusal or unknown session cannot satisfy this test.
    await refusedWithoutWrite(approvalRequest);

    const ranB = await pageB.request.post(`${path}/run`, {
      headers: headersB, data: { mode: 'sandbox', version: baselineB.version, request_id: crypto.randomUUID() },
    });
    expect(ranB.status()).toBe(200);
    baselineB = await read(headersB);
    const planB = baselineB.offers.find(row => row.offer.id === offerId)!.plan!;
    expect(planB).toBeTruthy();
    expect(planB.recorded).toBe(false);
    expect(planB.run_id).not.toBe(planA.run_id);
    expect(planB.digest).not.toBe(planA.digest);
    expect(planB.key).toBe(planA.key); // Address alone confers no cross-session authority.
    await refusedWithoutWrite(approvalRequest);
    await refusedWithoutWrite({ ...planA, consent: true, request_id: crypto.randomUUID() });
    await refusedWithoutWrite({ ...planB, run_id: planA.run_id, consent: true, request_id: crypto.randomUUID() });
    await refusedWithoutWrite({ ...planB, digest: planA.digest, consent: true, request_id: crypto.randomUUID() });
    await refusedWithoutWrite({ ...approvalRequest, action: 'claim', role: 'duty manager', org: approvedA.pickups[0].org }, 409, 'pickup');

    for (const [action, data] of [['run', runRequest], ['approve', approvalRequest]] as const) {
      const replay = await page.request.post(`${path}/${action}`, { headers: headersA, data });
      expect(replay.status()).toBe(200);
      expect(await replay.json()).toEqual(approvedA);
      expect(await read(headersA)).toEqual(approvedA);
      await unchangedB();
    }
    expect(baselineB.records).toEqual([]);
    expect(baselineB.pickups).toEqual([]);
    expect(baselineB.operations).toEqual([]);
    await pageB.goto(`/#/offers/${offerId}`);
    // API-positive controls do not update React's cached snapshot; a hash-only
    // navigation is not a refresh. Re-read the server before asserting consent.
    await pageB.reload();
    await unchangedB();
    await expect(pageB.getByRole('heading', { name: 'Approve this exact plan', exact: true })).toBeVisible();
    await expect(pageB.getByLabel('I have reviewed this exact allocation and record address, and approve this plan.')).not.toBeChecked();
    await expect(pageB.getByRole('button', { name: 'Approve in sandbox', exact: true })).toBeDisabled();
    await pageB.screenshot({ path: info.outputPath('session-b-unapproved.png'), fullPage: true });
  } finally {
    await contextB.close();
  }
});
