import { calendarDay, dateCue } from './dispatch';
import type { OfferRow, Pickup, Workspace } from './types';

export const filters = { all: 'All offers', allocated: 'Computed allocations', unallocated: 'Unallocated quantity', pending: 'Pending pickups', confirmed: 'Confirmed collections', urgent: 'Due soon or overdue', unknown: 'Allocation unknown' };
export type Filter = keyof typeof filters;
const pendingStates = new Set(['unclaimed', 'claimed', 'scheduled', 'overdue']);
export const amount = (value: number) => new Intl.NumberFormat('en', { maximumFractionDigits: 6 }).format(value);
const validQuantity = (value: number) => Number.isFinite(value) && value >= 0;

// Identical repeated projections count once. Contradictory identities are withheld,
// never resolved by array order or counted twice.
export function uniqueRows<T>(rows: T[], identity: (row: T) => string) {
  const values = new Map<string, T>();
  const conflicts = new Set<string>();
  for (const row of rows) {
    const id = identity(row);
    if (values.has(id) && JSON.stringify(values.get(id)) !== JSON.stringify(row)) conflicts.add(id);
    else values.set(id, row);
  }
  return { rows: [...values].filter(([id]) => !conflicts.has(id)).map(([, row]) => row), conflicts: conflicts.size };
}
export function projection(data: Workspace) {
  const offers = uniqueRows(data.offers, row => row.offer.id);
  const pickups = uniqueRows(data.pickups, row => JSON.stringify([row.offer_id, row.org, row.commitment_digest || row.plan_digest]));
  const records = uniqueRows(data.records, row => row.key);
  return { offers: offers.rows, pickups: pickups.rows, records: records.rows, conflicts: offers.conflicts + pickups.conflicts + records.conflicts };
}
export function allocationTotal(row: OfferRow): number | null {
  if (!validQuantity(row.offer.quantity) || !row.offer.unit || ['not_started', 'running', 'failed', 'blocked', 'refused_by_gate'].includes(row.status)) return null;
  const allocations = row.result.draft_allocations;
  if (!Array.isArray(allocations)) return null;
  if (!row.plan && row.result.outcome !== 'nothing_to_allocate') return null;
  if (row.plan && (!row.result.run_id || row.plan.run_id !== row.result.run_id)) return null;
  const unique = uniqueRows(allocations, item => item.org);
  if (unique.conflicts || unique.rows.some(item => !item.org || !validQuantity(item.quantity))) return null;
  const total = unique.rows.reduce((sum, item) => sum + item.quantity, 0);
  return Number.isFinite(total) && total <= row.offer.quantity + 1e-6 ? total : null;
}
export function isPending(item: Pickup) { return pendingStates.has(item.state); }
export function isConfirmed(item: Pickup) { return item.state === 'confirmed'; }
export function isUrgent(row: OfferRow, today: string) {
  if (row.plan?.recorded) return false;
  const cue = dateCue(row.offer, today);
  return cue.tone === 'past' || cue.tone === 'soon';
}
export function filterOffers(data: Workspace, filter: Filter, unit: string, today: string, query = '') {
  const source = projection(data);
  return source.offers.filter(row => {
    if (unit && row.offer.unit !== unit) return false;
    if (!`${row.offer.title} ${row.offer.id} ${row.offer.donor}`.toLowerCase().includes(query.toLowerCase())) return false;
    const total = allocationTotal(row);
    switch (filter) {
      case 'allocated': return total !== null;
      case 'unallocated': return total !== null && row.offer.quantity - total > 1e-6;
      case 'unknown': return total === null;
      case 'pending': return source.pickups.some(p => p.offer_id === row.offer.id && isPending(p));
      case 'confirmed': return source.pickups.some(p => p.offer_id === row.offer.id && isConfirmed(p));
      case 'urgent': return isUrgent(row, today);
      default: return true;
    }
  });
}
export function metrics(data: Workspace, unit: string, today: string) {
  const source = projection(data);
  const offers = source.offers.filter(row => !unit || row.offer.unit === unit);
  const pickups = source.pickups.filter(row => !unit || row.unit === unit);
  let offered = 0, allocated = 0, unallocated = 0, unknown = 0, quantityUnknown = 0;
  for (const row of offers) {
    if (validQuantity(row.offer.quantity) && row.offer.unit) offered += row.offer.quantity;
    else quantityUnknown++;
    const total = allocationTotal(row);
    if (total === null) unknown++;
    else { allocated += total; unallocated += row.offer.quantity - total; }
  }
  // Callers select one unit for quantity metrics. Never sum kg and units.
  const mixed = new Set(offers.map(row => row.offer.unit)).size > 1;
  return { offered: mixed || quantityUnknown ? null : offered, allocated: mixed || unknown === offers.length && offers.length > 0 ? null : allocated,
    unallocated: mixed || unknown === offers.length && offers.length > 0 ? null : Math.max(0, unallocated), unknown,
    pending: pickups.filter(isPending).length, confirmed: pickups.filter(isConfirmed).length,
    urgent: offers.filter(row => isUrgent(row, today)).length, count: offers.length, conflicts: source.conflicts };
}
export function priorityOffers(data: Workspace, today: string) {
  return projection(data).offers.filter(row => !row.plan?.recorded || data.pickups.some(p => p.offer_id === row.offer.id && isPending(p)))
    .sort((a, b) => Number(isUrgent(b, today)) - Number(isUrgent(a, today)) ||
      (calendarDay(a.offer.collection_date) ?? Infinity) - (calendarDay(b.offer.collection_date) ?? Infinity) || a.offer.id.localeCompare(b.offer.id));
}
const stoppedOutcomes = new Set(['blocked', 'refused_by_gate', 'nothing_to_allocate']);
// A run that stopped with a reason and produced no plan leaves nothing to approve.
export function isStopped(row: OfferRow) { return !row.plan && stoppedOutcomes.has(row.status); }
export type StartState = { kind: 'empty' } | { kind: 'first' } | { kind: 'returning'; next: OfferRow; recorded: number; total: number } | { kind: 'completed'; stopped: number };
// The Dashboard start state comes only from the loaded workspace: no stored flag, route or extra request decides it.
export function startState(data: Workspace, today: string): StartState {
  const source = projection(data);
  if (!source.offers.length) return { kind: 'empty' };
  const progressed = source.records.length > 0 || source.pickups.length > 0 || source.offers.some(row => row.status !== 'not_started' || !!row.result.run_id || !!row.plan);
  if (!progressed) return { kind: 'first' };
  const collecting = (row: OfferRow) => source.pickups.some(p => p.offer_id === row.offer.id && isPending(p));
  const open = priorityOffers(data, today).filter(row => collecting(row) || (!row.plan?.recorded && !isStopped(row)));
  // Decisions still to approve come before collections still to close.
  const next = open.find(row => !row.plan?.recorded) || open[0];
  return next ? { kind: 'returning', next, recorded: source.offers.filter(row => row.plan?.recorded).length, total: source.offers.length }
    : { kind: 'completed', stopped: source.offers.filter(isStopped).length };
}
export interface Activity { id: string; offerId: string; title: string; detail: string; at: number | null }
export function activity(data: Workspace): Activity[] {
  const source = projection(data);
  const timestamp = (n: number | null | undefined) => typeof n === 'number' && Number.isFinite(n) && n > 0 ? n : null;
  return [
    ...source.records.map(r => ({ id: `record-${r.key}`, offerId: r.offer_id, title: r.mode === 'sandbox' ? 'Allocation recorded in sandbox' : 'Allocation published', detail: r.key + (r.superseded_by ? ` · Superseded by ${r.superseded_by}` : ''), at: timestamp(r.published_at) })),
    ...source.pickups.filter(p => p.state !== 'unclaimed').map(p => ({ id: `pickup-${p.offer_id}-${p.org}-${p.commitment_digest || p.plan_digest}`, offerId: p.offer_id,
      title: isConfirmed(p) ? 'Collection explicitly confirmed' : p.state === 'invalidated' ? 'Commitment invalidated' : p.state === 'claimed' ? 'Share claimed' : 'Collection scheduled',
      detail: `${p.org} · ${amount(p.quantity)} ${p.unit}${p.agreed_at ? ` · Scheduled for ${p.agreed_at}` : ''}`,
      // An agreed future pickup time is not the time the scheduling action happened.
      at: isConfirmed(p) ? timestamp(p.confirmed_at) : p.state === 'claimed' ? timestamp(p.claimed_at) : null })),
  ].sort((a, b) => (b.at ?? -Infinity) - (a.at ?? -Infinity) || a.id.localeCompare(b.id));
}
