import { expect, it, vi } from 'vitest';
import { readPreference, removePreference, storageBlocked, writePreference } from './storage';
it('preserves preferences and removes handles', () => {
  expect(readPreference('missing')).toBeNull(); writePreference('preference','live');
  expect(readPreference('preference')).toBe('live'); removePreference('preference'); expect(readPreference('preference')).toBeNull();
});
it('keeps the tab usable when browser storage is blocked', () => {
  vi.spyOn(window,'localStorage','get').mockImplementation(() => {throw new DOMException('blocked');});
  writePreference('blocked-session','session'); expect(readPreference('blocked-session')).toBe('session');
  expect(readPreference('absent')).toBeNull(); expect(storageBlocked()).toBe(true);
  removePreference('blocked-session'); expect(readPreference('blocked-session')).toBeNull();
});
