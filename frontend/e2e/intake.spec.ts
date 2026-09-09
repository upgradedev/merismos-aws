import { expect, test } from '@playwright/test';

for (const flow of ['success', 'refusal', 'correction'] as const) {
  test(`Editable ${flow} flow uses real HTTP and preserves refused-input recovery`, async ({page}, info) => {
    await page.goto('/#/offers/new');
    await page.getByRole('button', {name: `Try ${flow}`, exact: true}).click();
    const note = page.getByLabel("Donor's food and collection note");
    const original = await note.inputValue();
    const response = page.waitForResponse(r => r.url().endsWith('/api/offers/new') && r.request().method() === 'POST');
    await page.getByRole('button', {name: 'Add to sandbox'}).click();
    expect((await response).status()).toBe(flow === 'correction' ? 400 : 200);
    if (flow === 'correction') {
      await expect(page.getByRole('alert')).toContainText('phone number');
      await expect(note).toHaveValue(original);
      await note.fill('Invented donation; collect before evening.');
      await page.getByRole('button', {name: 'Add to sandbox'}).click();
    }
    await page.getByRole('button', {name: 'Work out the split'}).click();
    if (flow === 'refusal') {
      await expect(page.getByRole('button', {name: 'Approve in sandbox'})).toHaveCount(0);
      await expect(page.getByText(/cold chain/i).first()).toBeVisible();
    } else {
      await expect(page.getByRole('heading', {name: 'Approve this exact plan'})).toBeVisible();
      await page.getByLabel(/I have reviewed this exact allocation/).check();
      await page.getByRole('button', {name: 'Approve in sandbox'}).click();
      await expect(page.getByRole('heading', {name: 'The recorded plan'})).toBeVisible();
    }
    await page.getByText('Evidence bundle and recovery', {exact: true}).click();
    await expect(page.getByLabel('Evidence bundle', {exact: true})).toContainText('Hashes bind bytes');
    await expect(page.getByLabel('Evidence bundle', {exact: true})).toContainText('not measured');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: info.outputPath(`editable-${flow}.png`), fullPage: true});
  });
}

test('Human intake to split, exact approval and collection, with invalid field recovery', async ({page}, info) => {
  await page.goto('/#/offers/new');
  await expect(page.getByRole('heading',{name:'Add an offer'})).toBeVisible();
  await page.getByLabel('What is being donated?').fill('Synthetic courtyard vegetables');
  await page.getByLabel('Donor organisation').fill('Demonstration greengrocer');
  await page.getByLabel('Quantity',{exact:true}).fill('120.25');
  await page.getByLabel('Collection date',{exact:true}).fill('2026-09-12');
  await page.getByLabel('Use by date (if known)').fill('2026-09-14');
  await page.getByLabel("Donor's food and collection note").fill('Call 6941234567');
  await page.getByRole('button',{name:'Add to sandbox'}).click();
  await expect(page.getByRole('alert')).toContainText('phone number');
  await expect(page.getByLabel('Quantity',{exact:true})).toHaveValue('120.25');
  await page.getByLabel("Donor's food and collection note").fill('Invented produce, collect before evening.');
  await page.getByRole('button',{name:'Add to sandbox'}).click();
  await expect(page.getByRole('heading',{name:'Synthetic courtyard vegetables'})).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading',{name:'Synthetic courtyard vegetables'})).toBeVisible();
  await page.getByRole('button',{name:'Work out the split'}).click();
  await expect(page.getByRole('heading',{name:'Approve this exact plan'})).toBeVisible();
  await page.getByLabel(/I have reviewed this exact allocation/).check();
  await page.getByRole('button',{name:'Approve in sandbox'}).click();
  await expect(page.getByRole('heading',{name:'The recorded plan'})).toBeVisible();
  await page.getByRole('link',{name:'Open collection tasks →'}).click();
  await expect(page.getByRole('heading',{name:'Pickups',exact:true})).toBeVisible();
  const card=page.getByRole('article').filter({has:page.getByRole('heading',{name:'Omonoia Soup Kitchen',exact:true})});
  await card.getByRole('button',{name:'Claim this share'}).click();
  await expect(card.getByText('Claimed',{exact:true})).toBeVisible();
  await card.getByLabel('This collection actually happened in the simulation.').check();
  await card.getByRole('button',{name:'Confirm collection'}).click();
  await page.getByLabel('Show').selectOption('confirmed');
  await expect(page.getByText('Confirmed collected')).toBeVisible();
  await page.screenshot({path:info.outputPath('intake-to-collection.png'),fullPage:true});
});

test('Storage-blocked browser keeps a usable in-tab sandbox', async ({page}) => {
  await page.addInitScript(() => Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Storage blocked');}}));
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'Dashboard',exact:true})).toBeVisible();
  await expect(page.getByText(/Browser storage is unavailable/)).toBeVisible();
  await page.getByText('End of day bread and vegetables',{exact:true}).click();
  await expect(page.getByRole('heading',{name:'End of day bread and vegetables',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Work out the split'}).click();
  await expect(page.getByRole('heading',{name:'Approve this exact plan'})).toBeVisible();
});
