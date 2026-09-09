import { expect, test } from '@playwright/test';
import type { Workspace } from '../src/types';

test('ME01/02/03: exact sandbox approval, persistent claim, scheduled and confirmed collection', async ({ page, context }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  // Freeze only the browser calendar so the seeded collection date is tomorrow.
  // Scheduling and all persisted server state still use the real HTTP backend.
  await page.clock.setFixedTime(new Date('2026-09-07T12:00:00Z'));
  await page.emulateMedia({reducedMotion: 'no-preference'});
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
  await expect(page.getByText('Synthetic demo', { exact: true })).toBeVisible();
  await expect(page.getByText(/Calendar cues use your browser-local date at view opening/)).toBeVisible();
  const upcoming = page.locator('.date-cue-soon .date-cue-label').first();
  await expect(upcoming).toHaveCSS('font-size', '14px');
  await expect(upcoming).toHaveCSS('animation-name', 'dispatch-date-cue');
  await expect(upcoming).toHaveCSS('animation-duration', '1.6s');
  await expect(upcoming).toHaveCSS('animation-iteration-count', '2');
  await page.emulateMedia({reducedMotion: 'reduce'});
  await expect(upcoming).toHaveCSS('animation-name', 'none');
  await expect(page.locator('.sidebar nav a').first()).toHaveCSS('transition-duration', '0s');
  await page.screenshot({path: info.outputPath('dispatch-inbox.png'), fullPage: true});
  await page.getByText('End of day bread and vegetables', { exact: true }).click();
  const runResponse = page.waitForResponse(response => response.url().endsWith('/api/offers/offer-4471/run') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Work out the split' }).click();
  const response = await runResponse;
  expect(response.status()).toBe(200);
  const state: Workspace = await response.json();
  const offer = state.offers.find(item => item.offer.id === 'offer-4471')!;
  // Required on BOTH CI and MERISMOS_UI_URL: an old backend's UI fallback
  // must not turn an undeployed projection into passing AWS release evidence.
  expect(offer.result.fairness_cap).toEqual({share: 0.4, source: 'registers/allocation-policy.md'});
  expect(offer.offer.quantity).toBe(240);
  await info.attach('fairness-cap-runtime.json', {body: JSON.stringify({offer_id: offer.offer.id, quantity: offer.offer.quantity, fairness_cap: offer.result.fairness_cap}), contentType: 'application/json'});
  await expect(page.getByRole('heading', { name: 'Approve this exact plan' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Omonoia Soup Kitchen' })).toBeVisible();
  await expect(page.getByText('124 kg', { exact: true })).toBeVisible();
  await expect(page.getByRole('meter', {name: 'Elpida Night Shelter: allocated share'})).toHaveAttribute('aria-valuenow', '20');
  await expect(page.getByRole('meter', {name: 'Elpida Night Shelter: allocated share'})).toHaveAttribute('aria-valuemax', '240');
  await expect(page.getByRole('meter', {name: 'Elpida Night Shelter: policy ceiling'})).toHaveAttribute('aria-valuenow', '96');
  await expect(page.getByRole('meter', {name: 'Elpida Night Shelter: policy ceiling'})).toHaveAttribute('aria-valuemax', '240');
  for (const selector of ['.bar-heading', '.custody-pill', '.digest-copy', '.digest-label']) {
    await expect(page.locator(selector).first()).toHaveCSS('font-size', '14px');
  }
  for (const selector of ['.allocation-list p', '.allocation-scale', '.digest-explanation']) {
    await expect(page.locator(selector).first()).toHaveCSS('font-size', '16px');
  }
  const bar = page.getByRole('meter', {name: 'Elpida Night Shelter: allocated share'}).locator('span');
  await expect(bar).toHaveCSS('animation-name', 'none');
  await expect(bar).toHaveCSS('transition-duration', '0s');
  await page.emulateMedia({reducedMotion: 'no-preference'});
  await expect(bar).toHaveCSS('animation-name', 'allocation-grow');
  await expect(bar).toHaveCSS('animation-duration', '0.4s');
  await expect(bar).toHaveCSS('animation-iteration-count', '1');
  await page.emulateMedia({reducedMotion: 'reduce'});
  await expect(page.getByRole('textbox', {name: 'Approval content digest'})).toHaveValue(offer.plan!.digest);
  await page.getByRole('button', {name: 'Copy digest'}).click();
  await expect(page.getByText('Digest copied. Record status is unchanged.')).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(offer.plan!.digest);
  await expect(page.getByText('Draft · approval still required')).toBeVisible();
  const session = await page.evaluate(() => localStorage.getItem('merismos.session'));
  const afterCopy = await page.request.get('/api/workspace?mode=sandbox', {headers: {'X-Merismos-Session': session!}});
  expect(afterCopy.status()).toBe(200);
  expect((await afterCopy.json()).version).toBe(state.version);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: 'Approve in sandbox' })).toBeDisabled();
  await page.getByText('Read the exact record text', { exact: true }).click();
  await expect(page.locator('pre')).toContainText('Elpida');
  await page.getByText('Share allocation reasons', {exact: true}).click();
  await expect(page.getByLabel('Shareable reasons summary')).toContainText('DRAFT');
  await page.screenshot({ path: info.outputPath('approval.png'), fullPage: true });
  await page.getByLabel('I have reviewed this exact allocation and record address, and approve this plan.').check();
  await page.getByRole('button', { name: 'Approve in sandbox' }).click();
  await expect(page.getByRole('heading', { name: 'The recorded plan' })).toBeVisible();
  await expect(page.getByText('Sandbox record · server reported')).toBeVisible();
  await expect(page.getByText('Digest copied. Record status is unchanged.')).toHaveCount(0);
  await page.getByRole('link', { name: 'Open collection tasks →' }).click();
  const kitchen = page.getByRole('article').filter({has: page.getByRole('heading', {name: 'Omonoia Soup Kitchen'})});
  await kitchen.getByRole('combobox', { name: 'Collecting role', exact: true }).selectOption('kitchen lead');
  await kitchen.getByRole('button', { name: 'Claim this share' }).click();
  await expect(kitchen.getByText('Claimed', { exact: true })).toBeVisible();
  await page.reload();
  await expect(kitchen.getByText('Collecting role: kitchen lead')).toBeVisible();
  const tomorrow = new Date(Date.now() + 86400_000).toISOString().slice(0, 16);
  await kitchen.getByLabel('Collection time (your local time)').fill(tomorrow);
  await kitchen.getByRole('button', { name: 'Save collection time' }).click();
  await expect(kitchen.getByText('Scheduled', { exact: true })).toBeVisible();
  await expect(kitchen.getByRole('button', { name: 'Confirm collection' })).toBeDisabled();
  await kitchen.getByLabel('This collection actually happened in the simulation.').check();
  await kitchen.getByRole('button', { name: 'Confirm collection' }).click();
  await page.getByLabel('Show').selectOption('confirmed');
  await expect(kitchen.getByText('Confirmed collected')).toBeVisible();
  await expect(kitchen.getByText('Recorded date', {exact: true})).toBeVisible();
  await expect(kitchen.getByRole('button', { name: 'Claim this share' })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('confirmed-pickup.png'), fullPage: true });
  await page.getByRole('link', { name: 'History', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sandbox history' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'records/offer-4471.md' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('link', { name: 'records/offer-4471.md' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.evaluate(() => Object.keys(localStorage).sort())).toEqual(['merismos.session']);
  expect(errors).toEqual([]);
});

test('Safety refusal, empty filters, deep link and live read-only boundary', async ({ page }, info) => {
  await page.goto('/#/offers/offer-4477');
  await page.getByRole('button', { name: 'Work out the split' }).click();
  await expect(page.getByText('Safety refusal', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve in sandbox' })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('refusal.png'), fullPage: true });
  await page.getByRole('link', { name: 'All offers' }).click();
  await page.getByRole('searchbox', { name: 'Search offers' }).fill('no such donation');
  await expect(page.getByRole('heading', { name: 'No offers match' })).toBeVisible();
  await page.getByLabel('Workspace', { exact: true }).selectOption('live');
  await expect(page.getByRole('heading', { name: 'Offers', exact: true })).toBeVisible();
  await page.getByText('End of day bread and vegetables', { exact: true }).click();
  // Live data already has runs and may already have a recorded plan. Assert
  // the authorization boundary, not the empty local fixture's initial label.
  const session = await page.evaluate(() => localStorage.getItem('merismos.session'));
  const headers = {'X-Merismos-Session': session!};
  const response = await page.request.get('/api/workspace?mode=live', {headers});
  expect(response.status()).toBe(200);
  const live = await response.json();
  expect(live.can_write).toBe(false);
  const offer = live.offers.find((item: {offer: {id: string}}) => item.offer.id === 'offer-4471');
  expect(offer).toBeDefined();
  const actionCard = page.locator('.action-card');
  if (offer.plan?.recorded) {
    await expect(actionCard.getByRole('link', {name: 'Open collection tasks →'})).toBeVisible();
    await expect(actionCard.getByRole('button')).toHaveCount(0);
  } else {
    await expect(actionCard.getByRole('button', {name: /^(Work out the split|Re-run the fleet)$/})).toBeDisabled();
  }
  await expect(actionCard.getByText(/Live changes require an authenticated/)).toBeVisible();
  const denied = await page.request.post('/api/offers/offer-4471/run', {
    headers, data: {mode:'live', version:live.version, request_id:crypto.randomUUID()},
  });
  expect(denied.status()).toBe(403);
  expect((await denied.json()).detail).toContain('authenticated network coordinator');
  await expect(page.getByText('Synthetic demo', { exact: true })).toBeVisible();
});

test('Real HTTP contract rejects stale consent, session crossover and duplicate collection', async ({ request }) => {
  const create = await request.post('/api/sessions', {data: {}});
  const {session} = await create.json();
  const headers = {'X-Merismos-Session': session};
  const read = async () => (await request.get('/api/workspace?mode=sandbox', {headers})).json();
  let state = await read();
  const send = (kind: string, data: Record<string, unknown>) => request.post(`/api/offers/offer-4471/${kind}`, {headers, data: {...data, mode:'sandbox', version:state.version, request_id:crypto.randomUUID()}});
  const run = await send('run', {}); expect(run.ok()).toBe(true); state = await run.json();
  const plan = state.offers.find((o: {offer: {id: string}}) => o.offer.id === 'offer-4471').plan;
  expect((await send('approve', {...plan, consent:false})).status()).toBe(400);
  expect((await send('approve', {...plan, digest:'changed', consent:true})).status()).toBe(409);
  expect((await request.get('/api/workspace?mode=sandbox', {headers:{'X-Merismos-Session':'x'.repeat(43)}})).status()).toBe(410);
  const approved = await send('approve', {...plan, consent:true}); expect(approved.ok()).toBe(true); state = await approved.json();
  const org = 'Omonoia Soup Kitchen';
  const claimed = await send('pickup', {...plan, org, role:'duty manager', action:'claim'}); expect(claimed.ok()).toBe(true); state = await claimed.json();
  const confirmed = await send('pickup', {...plan, org, action:'confirm', consent:true}); expect(confirmed.ok()).toBe(true); state = await confirmed.json();
  expect((await send('pickup', {...plan, org, action:'confirm', consent:true})).status()).toBe(409);
  expect((await send('run', {})).status()).toBe(409);
});
