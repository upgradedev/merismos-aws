import { expect, test } from '@playwright/test';
import type { Workspace } from '../src/types';

test('ME7: unknown returning session requires explicit isolated restart without replay, including back and reload', async ({page}, info) => {
  await page.goto('/');
  await expect(page.getByRole('heading', {name: 'Dashboard', exact: true})).toBeVisible();
  const original = await page.evaluate(() => localStorage.getItem('merismos.session'));
  const headers = {'X-Merismos-Session': original!};
  const read = async (): Promise<Workspace> => {
    const response = await page.request.get('/api/workspace?mode=sandbox', {headers});
    expect(response.status()).toBe(200); return response.json();
  };
  const before = await read();
  await page.getByRole('navigation', {name: 'Main navigation'}).getByRole('link', {name: 'History'}).click();
  await expect(page.getByRole('heading', {name: 'Sandbox history'})).toBeVisible();
  await page.evaluate(() => localStorage.setItem('merismos.session', 'unknown-demo-session'.padEnd(43, '_')));
  const writes: string[] = [];
  page.on('request', request => { if (request.method() === 'POST') writes.push(new URL(request.url()).pathname); });
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('expired, be unknown or have had access revoked');
  expect(writes).toEqual([]);
  await page.getByRole('button', {name: 'Refresh and review'}).click();
  await expect(page.getByRole('button', {name: 'Start a new sandbox'})).toBeEnabled();
  expect(writes).toEqual([]);
  await page.getByRole('button', {name: 'Start a new sandbox'}).focus(); await page.keyboard.press('Enter');
  await page.getByRole('button', {name: 'Keep previous workspace'}).focus(); await page.keyboard.press('Enter');
  expect(writes).toEqual([]);
  await page.getByRole('button', {name: 'Start a new sandbox'}).click();
  await page.screenshot({path: info.outputPath('me7-explicit-recovery.png'), fullPage: true});
  await page.getByRole('button', {name: 'Create isolated workspace'}).focus(); await page.keyboard.press('Enter');
  await expect(page.getByRole('status')).toContainText('New isolated workspace ready');
  expect(writes).toEqual(['/api/sessions']);
  const replacement = await page.evaluate(() => localStorage.getItem('merismos.session'));
  expect(replacement).not.toBe(original);
  expect(await page.evaluate(() => localStorage.getItem(`merismos.retained-session.${'unknown-demo-session'.padEnd(43, '_')}`))).toBe('unknown-demo-session'.padEnd(43, '_'));
  expect(await read()).toEqual(before);
  await page.goBack();
  await expect(page.getByRole('heading', {name: 'This address belongs to the previous workspace'})).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', {name: 'This address belongs to the previous workspace'})).toBeVisible();
  expect(writes).toEqual(['/api/sessions']);
  await page.getByRole('link', {name: 'Open the current dashboard'}).click();
  await expect(page.getByRole('heading', {name: 'Dashboard', exact: true})).toBeVisible();
  const freshResponse = await page.request.get('/api/workspace?mode=sandbox', {headers: {'X-Merismos-Session': replacement!}});
  const fresh: Workspace = await freshResponse.json();
  expect(fresh.records).toEqual([]); expect(fresh.pickups).toEqual([]); expect(fresh.operations).toEqual([]);
  await info.attach('recovery-outcome.json', {body: JSON.stringify({fixture: 'unknown-token, not aged TTL', writes, previousWorkspaceUnchanged: true, freshVersion: fresh.version}), contentType: 'application/json'});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('ME7: missing returning handle pauses without creating a replacement or losing the URL', async ({page}) => {
  await page.goto('/#/workspace?offer=offer-999999');
  await expect(page.getByRole('heading', {name: 'Offer not found'})).toBeVisible();
  await page.evaluate(() => localStorage.removeItem('merismos.session'));
  const requests: string[] = [];
  page.on('request', request => { if (request.method() === 'POST') requests.push(request.url()); });
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('saved session handle is missing');
  await expect(page).toHaveURL(/offer=offer-999999/);
  await page.getByRole('button', {name: 'Refresh and review'}).click();
  await expect(page.getByRole('button', {name: 'Start a new sandbox'})).toBeEnabled();
  expect(requests).toEqual([]);
});

test('ME7: storage refusal supports the current tab and requires explicit restart after reload', async ({page}, info) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', {get() { throw new DOMException('Storage refused'); }});
  });
  await page.goto('/#/offers/new');
  await expect(page.getByRole('heading', {name: 'Add an offer'})).toBeVisible();
  await expect(page.getByText(/Browser storage is unavailable/)).toBeVisible();
  await page.getByRole('button', {name: 'Try success', exact: true}).click();
  await page.getByLabel('What is being donated?').fill('Storage refusal demonstration produce');
  const added = page.waitForResponse(response => response.url().endsWith('/api/offers/new'));
  await page.getByRole('button', {name: 'Add to sandbox', exact: true}).click();
  expect((await added).status()).toBe(200);
  await expect(page.getByRole('heading', {name: 'Storage refusal demonstration produce', exact: true})).toBeVisible();
  const writes: string[] = [];
  page.on('request', request => { if (request.method() === 'POST') writes.push(new URL(request.url()).pathname); });
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('saved session handle is missing');
  expect(writes).toEqual([]);
  await page.getByRole('button', {name: 'Start a new sandbox'}).click();
  await page.getByRole('button', {name: 'Create isolated workspace'}).click();
  await expect(page.getByRole('status')).toContainText('New isolated workspace ready');
  expect(writes).toEqual(['/api/sessions']);
  await expect(page.getByRole('heading', {name: 'Offer not found'})).toBeVisible();
  await page.screenshot({path: info.outputPath('me7-storage-refusal.png'), fullPage: true});
});
