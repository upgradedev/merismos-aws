const memory = new Map<string, string>();
const pending = new Set<string>();
let blocked = false;
export function readPreference(key: string): string | null {
  if (pending.has(key)) return memory.get(key) ?? null;
  try {
    const value = localStorage.getItem(key);
    if (value === null) memory.delete(key); else memory.set(key, value);
    return value;
  }
  catch { blocked = true; return memory.get(key) ?? null; }
}
export function writePreference(key: string, value: string): void {
  memory.set(key, value);
  try { localStorage.setItem(key, value); pending.delete(key); } catch { blocked = true; pending.add(key); }
}
export function removePreference(key: string): void {
  memory.delete(key);
  try { localStorage.removeItem(key); pending.delete(key); } catch { blocked = true; pending.add(key); }
}
export function storageBlocked(): boolean { return blocked; }
