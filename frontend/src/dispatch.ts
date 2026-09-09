import type { Offer } from './types';

const DAY = 86_400_000;

// A calendar comparison, not elapsed shelf life. Parse date-only input without
// silently rolling impossible dates into a different month or applying a timezone.
export function calendarDay(value: string | undefined): number | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const milliseconds = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(milliseconds) && new Date(milliseconds).toISOString().slice(0, 10) === value
    ? milliseconds / DAY : null;
}

export function localCalendarDate(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

export function dateCue(offer: Pick<Offer, 'collection_date' | 'use_by'> | undefined, today: string, closed = false) {
  const dates = [
    { label: 'Collection', value: offer?.collection_date },
    { label: 'Use by', value: offer?.use_by },
  ].flatMap(item => {
    const day = calendarDay(item.value);
    return day === null ? [] : [{ ...item, value: item.value!, day }];
  }).sort((a, b) => a.day - b.day);
  const next = dates[0];
  const now = calendarDay(today);
  if (!next) return { label: 'Date unavailable', date: '', kind: '', tone: 'unknown', detail: 'No valid collection or use-by date was supplied.' };
  const days = now === null ? null : next.day - now;
  const timing = closed ? 'Recorded date' : days === null ? 'Clock unavailable' : days < 0 ? 'Date passed'
    : days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : `In ${days} days`;
  return { label: timing, date: next.value, kind: next.label, tone: closed || days === null ? 'neutral'
    : days < 0 ? 'past' : days <= 1 ? 'soon' : 'neutral', detail: `${next.label}: ${next.value}` };
}
