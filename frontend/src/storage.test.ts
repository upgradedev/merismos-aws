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
it('a refused write cannot make readable stale storage override the current tab handle', () => {
  localStorage.setItem('partial-refusal-session', 'previous');
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Quota exceeded'); });
  writePreference('partial-refusal-session', 'replacement');
  expect(localStorage.getItem('partial-refusal-session')).toBe('previous');
  expect(readPreference('partial-refusal-session')).toBe('replacement');
});
it('a refused removal remains removed in this tab rather than resurrecting a stale handle', () => {
  localStorage.setItem('refused-removal', 'previous');
  vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new DOMException('Refused'); });
  removePreference('refused-removal');
  expect(readPreference('refused-removal')).toBeNull();
});
it('never resurrects a handle whose external deletion was already observed before storage fails', () => {
  localStorage.setItem('externally-removed-session', 'previous-valid-handle');
  expect(readPreference('externally-removed-session')).toBe('previous-valid-handle');
  // Removal is independent of our helper, like another tab or browser settings.
  localStorage.removeItem('externally-removed-session');
  expect(readPreference('externally-removed-session')).toBeNull();
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new DOMException('SecurityError'); });
  expect(readPreference('externally-removed-session')).toBeNull();
});
