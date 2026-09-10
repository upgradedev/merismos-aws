import { expect, test, devices, type BrowserContext, type Request } from '@playwright/test';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { allowedRequest, ORIGIN, plannedAttempts, REGISTRATION, summarize, type HttpSample, type Identity, type Measurement, type StageName } from '../src/dispatchMeasurement';
import type { Workspace } from '../src/types';

test('fixed20 preregistered source-only hero attempts (not20 acceptance tests)', async ({browser}) => {
  const source = execFileSync('git', ['rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
  if (source !== process.env.GITHUB_SHA || source === REGISTRATION) throw new Error('Measured checkout must match CI source, after registration.');
  execFileSync('git', ['merge-base', '--is-ancestor', REGISTRATION, source]);
  const current = JSON.parse(readFileSync('UAT.testbook.json', 'utf8')).x1_measurement_protocol;
  const registered = JSON.parse(execFileSync('git', ['show', `${REGISTRATION}:frontend/UAT.testbook.json`], {encoding: 'utf8'})).x1_measurement_protocol;
  if (JSON.stringify(current) !== JSON.stringify(registered) || registered.attempts !== 20 || registered.id !== 'merismos-source-hero-v1') throw new Error('Preregistered protocol changed; no measurement permitted.');
  const identity: Identity = {source_sha: source, protocol_commit: REGISTRATION, protocol_sha256: createHash('sha256').update(JSON.stringify(registered)).digest('hex'), run_id: process.env.GITHUB_RUN_ID || '', run_attempt: process.env.GITHUB_RUN_ATTEMPT || ''};
  const data: Measurement = {schema: 1, scope: 'SOURCE_ONLY', identity, attempts: plannedAttempts()};
  const environment = {browser: browser.version(), node: process.version, os: process.platform, origin: ORIGIN,
    backend: 'Real Python handler, scripted Strands, SQLite. External sockets denied by tests/http_server.py.',
    instrumentation: 'Monotonic Node performance.now wall time; browser automation, response-body observation and event-loop overhead included. No human think-time.',
    traffic: 'Browser request bodies and decoded response bodies. Headers, session tokens, bodies and query values are not retained.'};
  const directory = 'test-results/source-measurement'; mkdirSync(directory, {recursive: true});
  function persist() { writeFileSync(`${directory}/raw.json`, JSON.stringify({...data, environment, protocol: registered}, null, 2)); writeFileSync(`${directory}/summary.json`, JSON.stringify(summarize(data, identity), null, 2)); }
  persist(); // Every planned slot exists even if infrastructure stops this job later.
  const csv = 'title,donor,quantity,unit,category,collection_date,use_by,allergens,allergens_unknown,hours_unrefrigerated,note\nBenchmark vegetables,Demonstration cooperative,120,kg,produce,2026-09-14,2026-09-18,,true,,Invented donation for community meals\n';
  for (const attempt of data.attempts) {
    const origin = performance.now(); const now = () => performance.now() - origin;
    const holder: {context?: BrowserContext} = {};
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active: StageName = 'setup', unsafe = false;
    const collecting: Promise<void>[] = [], samples = new Map<Request, HttpSample>();
    attempt.status = 'running';
    async function stage<T>(name: StageName, action: () => Promise<T>): Promise<T> {
      active = name; const item = {name, start_ms: now(), end_ms: 0, status: 'ok' as 'ok' | 'failed'};
      attempt.stages.push(item);
      try { return await action(); }
      catch (error) { item.status = 'failed'; throw error; }
      finally { item.end_ms = now(); }
    }
    const flow = (async () => {
      let first!: Workspace, approved!: Workspace, originalDigest = '', offerId = '';
      const page = await stage('setup', async () => {
        const context = await browser.newContext(attempt.viewport === 'desktop' ? {...devices['Desktop Chrome'], viewport: {width: 1440, height: 1000}} : {...devices['iPhone 13'], viewport: {width: 390, height: 844}});
        holder.context = context;
        await context.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: ORIGIN});
        await context.route('**/*', route => {
          const request = route.request();
          if (!allowedRequest(request.url(), request.method(), request.postData())) { unsafe = true; return route.abort('blockedbyclient'); }
          return route.continue();
        });
        context.on('request', request => {
          const sample: HttpSample = {id: samples.size + 1, method: request.method(), path: new URL(request.url()).pathname, stage: active, start_ms: now(), end_ms: null, status: null, request_body_bytes: request.postDataBuffer()?.byteLength || 0, response_body_bytes: null, error: null};
          samples.set(request, sample); attempt.requests.push(sample);
        });
        context.on('response', response => { const sample = samples.get(response.request()); if (sample) sample.status = response.status(); });
        context.on('requestfailed', request => { const sample = samples.get(request); if (sample) { sample.end_ms = now(); sample.error = 'request_failed'; } });
        context.on('requestfinished', request => {
          const sample = samples.get(request); if (!sample) return;
          sample.end_ms = now();
          collecting.push((async () => {
            try { const response = await request.response(); if (response) sample.response_body_bytes = (await response.body()).byteLength; else sample.error = 'response_missing'; }
            catch { sample.error = 'body_unavailable'; }
          })());
        });
        const p = await context.newPage(); p.setDefaultTimeout(10_000);
        await p.goto(`${ORIGIN}/#/offers/new`);
        await p.getByText('Import a donor CSV instead', {exact: true}).click();
        await expect(p.getByLabel('Donor CSV file')).toBeEnabled(); return p;
      });
      await stage('csv_preview', async () => { await page.getByLabel('Donor CSV file').setInputFiles({name: 'benchmark.csv', mimeType: 'text/csv', buffer: Buffer.from(csv)}); await expect(page.getByLabel('Select CSV row 2')).toBeEnabled(); });
      await stage('file', async () => { await page.getByLabel('Select CSV row 2').check(); await page.getByRole('button', {name: 'File selected rows (1)'}).click(); await expect(page.getByRole('heading', {name: 'Benchmark vegetables', exact: true})).toBeVisible(); });
      await stage('allocate', async () => {
        const response = page.waitForResponse(r => r.url().endsWith('/run') && r.request().method() === 'POST');
        await page.getByRole('button', {name: 'Work out the split'}).click(); first = await (await response).json();
        const row = first.offers.find(o => o.offer.title === 'Benchmark vegetables')!; originalDigest = row.plan!.digest; offerId = row.offer.id;
        expect(offerId).not.toBe('offer-4471'); await expect(page.getByLabel(/I have reviewed this exact allocation/)).toBeVisible();
      });
      await stage('approve_original', async () => { await page.getByLabel(/I have reviewed this exact allocation/).check(); await page.getByRole('button', {name: 'Approve in sandbox'}).click(); await expect(page.getByRole('heading', {name: 'The recorded plan'})).toBeVisible(); });
      await stage('claim_original', async () => { await page.getByLabel('Pickup organisation').selectOption(JSON.stringify(['Omonoia Soup Kitchen', originalDigest])); await page.getByRole('button', {name: 'Claim this share'}).click(); await expect(page.getByText('Claimed', {exact: true})).toBeVisible(); });
      await stage('disrupt', async () => {
        await page.getByText('Rehearse a collection disruption', {exact: true}).click(); await page.getByLabel('Organisation affected').selectOption('Omonoia Soup Kitchen');
        await page.getByLabel('New collection capacity (kg)').fill('0'); await page.getByRole('button', {name: 'Record simulated disruption'}).click();
        await expect(page.getByText('Old allocation is no longer actionable.', {exact: false})).toBeVisible(); await page.reload();
        await expect(page.getByRole('region', {name: 'Before and after disruption'})).toContainText('Omonoia Soup Kitchen');
      });
      await stage('replan', async () => {
        const response = page.waitForResponse(r => r.url().endsWith('/run') && r.request().method() === 'POST'); await page.getByRole('button', {name: 'Re-run the fleet'}).click();
        const next: Workspace = await (await response).json(); const row = next.offers.find(o => o.offer.id === offerId)!;
        expect(row.plan!.digest).not.toBe(originalDigest); expect(row.replan!.before_digest).toBe(originalDigest);
        expect(row.result.draft_barred_because!['Omonoia Soup Kitchen']).toContain('capacity is zero');
        await expect(page.getByLabel(/I have reviewed this exact allocation/)).not.toBeChecked();
      });
      await stage('approve_new', async () => {
        await page.getByLabel(/I have reviewed this exact allocation/).check(); const response = page.waitForResponse(r => r.url().endsWith('/approve') && r.request().method() === 'POST');
        await page.getByRole('button', {name: 'Approve in sandbox'}).click(); approved = await (await response).json();
        expect(approved.records).toHaveLength(2); expect(approved.records.find(r => r.content_digest === originalDigest)?.superseded_by).toBeTruthy();
      });
      await stage('claim_new', async () => { const pickup = approved.pickups.find(p => p.offer_id === offerId && p.state === 'unclaimed')!; await page.getByLabel('Pickup organisation').selectOption(JSON.stringify([pickup.org, pickup.commitment_digest || pickup.plan_digest])); await page.getByRole('button', {name: 'Claim this share'}).click(); await expect(page.getByText('Claimed', {exact: true})).toBeVisible(); });
      await stage('schedule', async () => {
        const future = await page.evaluate(() => {const d = new Date(Date.now() + 3600_000); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;});
        await page.getByLabel('Collection time (your local time)').fill(future); await page.getByRole('button', {name: 'Save collection time'}).click(); await expect(page.getByText('Scheduled', {exact: true})).toBeVisible();
      });
      await stage('confirm', async () => { await page.getByLabel('This collection actually happened in the simulation.').check(); await page.getByRole('button', {name: 'Confirm collection'}).click(); await expect(page.getByText('Simulation confirmed', {exact: true})).toBeVisible(); });
      await stage('copy_manifest', async () => {
        await page.getByText('Pickup manifest · copy or download', {exact: true}).click(); await expect(page.getByLabel('Pickup manifest', {exact: true})).toHaveCount(1);
        await page.getByRole('button', {name: 'Copy pickup manifest'}).click(); const text = await page.evaluate(() => navigator.clipboard.readText());
        expect(text).toContain(originalDigest); expect(text).toContain('Isolated simulation');
      });
      await stage('download_manifest', async () => { const download = page.waitForEvent('download'); await page.getByRole('button', {name: 'Download pickup manifest'}).click(); const file = await download; expect(file.suggestedFilename()).toBe('merismos-pickup-manifest.txt'); expect(await file.failure()).toBeNull(); });
    })();
    try {
      await Promise.race([flow, new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('attempt_deadline')), 60_000); })]);
      attempt.status = 'success';
    } catch (error) {
      attempt.status = 'failed'; attempt.failure_stage = active;
      attempt.error = error instanceof Error && error.message === 'attempt_deadline' ? 'attempt_deadline' : 'journey_assertion_or_request_failed';
      await holder.context?.close(); await flow.catch(() => undefined);
    } finally {
      if (timer) clearTimeout(timer);
      await Promise.allSettled(collecting);
      attempt.elapsed_ms = now();
      if (unsafe) { attempt.status = 'failed'; attempt.failure_stage = active; attempt.error = 'out_of_scope_network_refused'; }
      await holder.context?.close(); persist();
    }
  }
  const summary = summarize(data, identity);
  expect(summary.issues, 'Raw measurements must be valid; no replacement attempt is allowed.').toEqual([]);
  expect(summary.succeeded, 'Every planned source attempt must finish; failures remain in raw.json.').toBe(20);
});
