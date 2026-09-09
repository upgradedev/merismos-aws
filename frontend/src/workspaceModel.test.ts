import { expect, it } from 'vitest';
import { activity, allocationTotal, filterOffers, isConfirmed, isPending, isUrgent, metrics, priorityOffers, projection, uniqueRows } from './workspaceModel';
import { parseRoute, routeLink } from './routes';
import { workspace } from './test/fixtures';
import type { Pickup } from './types';

const today = '2026-09-09';
const pickup = (state = 'claimed'): Pickup => ({ offer_id: 'offer-4471', title: 'Bread', org: 'Kitchen', quantity: 96, unit: 'kg', role: 'duty manager', state, agreed_at: '', plan_digest: 'plan', run_id: 'run' });
function sample() {
  const data = workspace();
  data.offers[0].result.draft_allocations!.push({ org: 'Shelter', quantity: 20, reason: 'Capacity cap', share_of_offer: 20 / 240 });
  data.offers.push({ ...structuredClone(data.offers[0]), offer: { ...data.offers[0].offer, id: 'offer-4483', title: 'Hampers', unit: 'units', quantity: 180 }, status: 'not_started', result: {}, plan: null });
  return data;
}
it('derives 116 allocated and 124 remaining from API quantities and never mixes units', () => {
  const data = sample();
  expect(metrics(data, 'kg', today)).toMatchObject({ offered: 240, allocated: 116, unallocated: 124, unknown: 0, pending: 0, confirmed: 0, urgent: 1 });
  expect(metrics(data, 'units', today)).toMatchObject({ offered: 180, allocated: null, unallocated: null, unknown: 1 });
  expect(metrics(data, '', today)).toMatchObject({ offered: null, allocated: null, unallocated: null });
});
it.each(['not_started', 'running', 'failed', 'blocked', 'refused_by_gate'])('does not infer zero allocation from %s', status => {
  const row = workspace().offers[0]; row.status = status;
  expect(allocationTotal(row)).toBeNull();
});
it.each([NaN, Infinity, -1])('withholds invalid offer and allocation quantities %s', quantity => {
  const row = workspace().offers[0]; row.offer.quantity = quantity; expect(allocationTotal(row)).toBeNull();
  expect(metrics({ ...workspace(), offers: [row] }, 'kg', today).offered).toBeNull();
  row.offer.quantity = 240; row.result.draft_allocations![0].quantity = quantity; expect(allocationTotal(row)).toBeNull();
});
it('requires a consistent run and valid, present allocation projection', () => {
  const row = workspace().offers[0];
  row.result.draft_allocations = undefined; expect(allocationTotal(row)).toBeNull();
  row.result.draft_allocations = []; row.plan = null; expect(allocationTotal(row)).toBeNull();
  row.result.outcome = 'nothing_to_allocate'; expect(allocationTotal(row)).toBe(0);
  row.plan = workspace().offers[0].plan; row.result.run_id = 'other'; expect(allocationTotal(row)).toBeNull();
  row.result.run_id = ''; expect(allocationTotal(row)).toBeNull();
  row.result.run_id = row.plan!.run_id; row.offer.unit = ''; expect(allocationTotal(row)).toBeNull();
  row.offer.unit = 'kg'; row.result.draft_allocations = [{ org: '', quantity: 10, reason: '', share_of_offer: 0 }]; expect(allocationTotal(row)).toBeNull();
  row.result.draft_allocations[0] = { org: 'Kitchen', quantity: 241, reason: '', share_of_offer: 1 }; expect(allocationTotal(row)).toBeNull();
});
it('deduplicates identical allocations but withholds conflicting recipients independent of order', () => {
  const row = workspace().offers[0]; const share = row.result.draft_allocations![0];
  row.result.draft_allocations!.push({ ...share }); expect(allocationTotal(row)).toBe(96);
  row.result.draft_allocations!.push({ ...share, quantity: 20 }); expect(allocationTotal(row)).toBeNull();
  row.result.draft_allocations!.reverse(); expect(allocationTotal(row)).toBeNull();
  expect(uniqueRows([{ id: 1 }, { id: 1 }], r => String(r.id))).toEqual({ rows: [{ id: 1 }], conflicts: 0 });
});
it('excludes contradictory identities and counts repeated offers, pickups and records once', () => {
  const data = sample(); data.offers.push(structuredClone(data.offers[0]));
  const p = pickup('confirmed'); data.pickups = [p, { ...p }];
  const record = { key: 'records/offer-4471.md', offer_id: 'offer-4471', run_id: 'run', content_digest: 'd', published_at: 123, superseded_by: '', mode: 'sandbox' as const };
  data.records = [record, { ...record }];
  expect(projection(data).offers).toHaveLength(2); expect(projection(data).records).toHaveLength(1); expect(metrics(data, 'kg', today).confirmed).toBe(1);
  data.pickups.push({ ...p, quantity: 20 }); data.offers.push({ ...structuredClone(data.offers[0]), status: 'failed' }); data.records.push({ ...record, content_digest: 'changed' });
  expect(projection(data)).toMatchObject({ conflicts: 3, pickups: [], records: [] });
});
it('separates unknown partial quantities from known subtotals and handles an empty scope', () => {
  const data = sample(); data.offers[1].offer.unit = 'kg';
  expect(metrics(data, 'kg', today)).toMatchObject({ offered: 420, allocated: 116, unallocated: 124, unknown: 1 });
  data.offers = []; expect(metrics(data, '', today)).toMatchObject({ offered: 0, allocated: 0, unallocated: 0, count: 0 });
});
it.each(['unclaimed', 'claimed', 'scheduled', 'overdue'])('%s is pending and never confirmed', state => {
  expect(isPending(pickup(state))).toBe(true); expect(isConfirmed(pickup(state))).toBe(false);
});
it('only explicit confirmed state counts, with invalidated confirmations excluded', () => {
  const data = sample(); data.pickups = [pickup(), { ...pickup('unclaimed'), org: 'School' }, { ...pickup('invalidated'), org: 'Library', confirmed_at: 100 }, { ...pickup('confirmed'), org: 'Shelter', confirmed_at: null }];
  expect(metrics(data, 'kg', today)).toMatchObject({ pending: 2, confirmed: 1 });
  expect(isPending(pickup('invalidated'))).toBe(false);
  expect(activity(data).find(e => e.title === 'Collection explicitly confirmed')?.at).toBeNull();
});
it('metric filters return the exact contributing records and preserve unit and search scope', () => {
  const data = sample(); data.pickups = [pickup(), { ...pickup('confirmed'), org: 'Shelter' }];
  for (const filter of ['allocated', 'unallocated', 'pending', 'confirmed', 'urgent'] as const) expect(filterOffers(data, filter, 'kg', today).map(r => r.offer.id)).toEqual(['offer-4471']);
  expect(filterOffers(data, 'unknown', '', today).map(r => r.offer.id)).toEqual(['offer-4483']);
  expect(filterOffers(data, 'all', 'units', today, 'HAMPERS')).toHaveLength(1);
  expect(filterOffers(data, 'all', '', today, 'missing')).toHaveLength(0);
  data.offers[0].result.draft_allocations![0].quantity = 220;
  expect(filterOffers(data, 'unallocated', '', today)).toHaveLength(0);
});
it('dates are explicit calendar cues, and recorded plans need pending pickups to enter priority', () => {
  const data = sample(); const row = data.offers[0];
  row.offer.collection_date = '2026-08-01'; expect(isUrgent(row, today)).toBe(true);
  row.plan!.recorded = true; expect(isUrgent(row, today)).toBe(false);
  expect(priorityOffers(data, today).map(r => r.offer.id)).toEqual(['offer-4483']);
  data.pickups = [pickup()]; expect(priorityOffers(data, today)).toHaveLength(2);
  data.offers[1].offer.collection_date = ''; data.offers[1].offer.use_by = ''; expect(isUrgent(data.offers[1], today)).toBe(false);
  expect(priorityOffers(data, today)[0].offer.id).toBe('offer-4471');
});
it('uses confirmation and claim timestamps, never invents a scheduling event time', () => {
  const data = sample(); data.pickups = [{ ...pickup('confirmed'), confirmed_at: 200 }, { ...pickup(), org: 'Pantry', claimed_at: 100 }, { ...pickup('scheduled'), org: 'Library', agreed_at: '2030-01-01T12:00:00Z' }, { ...pickup('invalidated'), org: 'School' }];
  data.records = [{ key: 'old', offer_id: 'offer-4471', run_id: 'old', content_digest: 'old', published_at: NaN, superseded_by: 'new', mode: 'live' }];
  expect(activity(data).map(e => e.at)).toEqual([200, 100, null, null, null]);
  expect(activity(data).find(e => e.title === 'Allocation published')?.detail).toContain('Superseded by new');
});
it.each([
  ['', 'dashboard'], ['/dashboard', 'dashboard'], ['/workspace', 'workspace'], ['/records', 'records'], ['/offers', 'records'], ['/offers/new', 'intake'], ['/offers/offer-4471', 'workspace'], ['/history', 'history'], ['/pickups', 'pickups'], ['/missing', 'missing'],
])('routes %s without losing the existing journey', (path, page) => expect(parseRoute(path).page).toBe(page));
it('round-trips selection, filter, unit and multiword query and rejects unrecognised filters', () => {
  const link = routeLink('/records', { offer: 'offer-4471', filter: 'pending', unit: 'units', query: 'bread & vegetables' });
  expect(parseRoute(link.slice(1))).toMatchObject({ offer: 'offer-4471', filter: 'pending', unit: 'units', query: 'bread & vegetables' });
  expect(routeLink('/dashboard')).toBe('#/dashboard');
  expect(parseRoute('/workspace?filter=__proto__').filter).toBe('all');
  expect(parseRoute('/offers/%broken').offer).toBe('%broken');
});
