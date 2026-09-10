import { mkdirSync, writeFileSync } from 'node:fs';
import { summarize, type Attempt, type Identity, type Measurement } from '../src/dispatchMeasurement';

export function measurementWriter(directory: string, data: Measurement, identity: Identity, details: Record<string, unknown>) {
  mkdirSync(directory, {recursive: true});
  return () => {
    writeFileSync(`${directory}/raw.json`, JSON.stringify({...details, ...data}, null, 2));
    writeFileSync(`${directory}/summary.json`, JSON.stringify(summarize(data, identity), null, 2));
  };
}

// The synchronous writer must finish BEFORE even invoking the async flow. If it
// fails, no browser/session work starts. Process interruption thereafter leaves
// a persisted running slot, distinguishable from the other not-run attempts.
export function startPersistedAttempt<T>(attempt: Attempt, persist: () => void, flow: () => T): T {
  attempt.status = 'running';
  persist();
  return flow();
}
