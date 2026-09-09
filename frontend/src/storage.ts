const memory = new Map<string, string>();
let blocked = false;
export function readPreference(key: string): string | null {
  try { return localStorage.getItem(key) ?? memory.get(key) ?? null; }
  catch { blocked = true; return memory.get(key) ?? null; }
}
export function writePreference(key: string, value: string): void {
  memory.set(key, value);
  try { localStorage.setItem(key, value); } catch { blocked = true; }
}
export function removePreference(key: string): void {
  memory.delete(key);
  try { localStorage.removeItem(key); } catch { blocked = true; }
}
export function storageBlocked(): boolean { return blocked; }
