import { expect, it } from 'vitest';
import { calendarDay, dateCue, localCalendarDate } from './dispatch';

it.each([undefined, '', '2026-9-1', '2026-02-30', '2026-13-01', '2026-01-01T12:00Z', 'not a date'])('rejects unknown or invalid date-only value %s', value => {
  expect(calendarDay(value)).toBeNull();
});
it('uses calendar days across leap days and local date components', () => {
  expect(calendarDay('2028-03-01')! - calendarDay('2028-02-29')!).toBe(1);
  expect(localCalendarDate(new Date(2026, 0, 2, 23, 59))).toBe('2026-01-02');
  const now = new Date();
  expect(localCalendarDate()).toBe(localCalendarDate(now));
});
it.each([
  ['2026-09-08', 'Date passed', 'past'], ['2026-09-09', 'Today', 'soon'],
  ['2026-09-10', 'Tomorrow', 'soon'], ['2026-09-12', 'In 3 days', 'neutral'],
])('compares the earliest supplied calendar date %s without an hourly countdown', (date, label, tone) => {
  expect(dateCue({ collection_date: date, use_by: '2026-09-15' }, '2026-09-09')).toMatchObject({ label, tone, date, kind: 'Collection' });
});
it('uses an earlier use-by date but never guesses missing dates or clock', () => {
  expect(dateCue({ collection_date: '2026-09-12', use_by: '2026-09-10' }, '2026-09-09')).toMatchObject({label: 'Tomorrow', kind: 'Use by'});
  expect(dateCue({ collection_date: 'bad', use_by: '2026-09-10' }, 'invalid')).toMatchObject({label: 'Clock unavailable'});
  expect(dateCue(undefined, '2026-09-09')).toMatchObject({label: 'Date unavailable'});
  expect(dateCue({ collection_date: '', use_by: '' }, '2026-09-09')).toMatchObject({label: 'Date unavailable'});
  expect(dateCue({ collection_date: '2026-01-01', use_by: '' }, '2026-09-09', true)).toMatchObject({label: 'Recorded date', tone: 'neutral'});
});
