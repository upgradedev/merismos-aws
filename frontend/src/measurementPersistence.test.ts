import { mkdtempSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, expect, it, vi } from 'vitest';
import { measurementWriter, startPersistedAttempt } from '../measurement/persistence';
import { plannedAttempts, REGISTRATION, type Identity, type Measurement } from './dispatchMeasurement';

const directories: string[] = [];
afterEach(() => { for (const directory of directories.splice(0)) rmSync(directory, {recursive: true, force: true}); });
function setupWriter() {
  const directory = mkdtempSync(join(tmpdir(), 'merismos-measurement-lifecycle-')); directories.push(directory);
  const identity: Identity = {source_sha: 'a'.repeat(40), protocol_commit: REGISTRATION, protocol_sha256: 'b'.repeat(64), run_id: '123', run_attempt: '1'};
  const data: Measurement = {schema: 1, scope: 'SOURCE_ONLY', identity, attempts: plannedAttempts()};
  const persist = measurementWriter(directory, data, identity, {environment: {kind: 'unit fixture'}});
  return {directory, data, persist, read: (name: string) => JSON.parse(readFileSync(join(directory, `${name}.json`), 'utf8'))};
}

it('the actual disk writer records running before flow starts, even without finally/completion', () => {
  const {data, persist, read} = setupWriter(); persist();
  expect(read('raw').attempts.map((a: {status: string}) => a.status)).toEqual(Array(20).fill('not_run'));
  const flow = vi.fn(() => {
    // Reading disk INSIDE flow proves order; an in-memory summarize fixture cannot.
    expect(read('raw').attempts[0].status).toBe('running');
    expect(read('summary')).toMatchObject({attempted: 1, interrupted: 1, not_run: 19, valid: false});
    throw new Error('simulated abrupt stop without completion persistence');
  });
  expect(() => startPersistedAttempt(data.attempts[0], persist, flow)).toThrow('simulated abrupt stop');
  expect(flow).toHaveBeenCalledOnce();
  expect(read('raw').attempts[0]).toMatchObject({status: 'running', stages: [], elapsed_ms: null});
  expect(read('raw').attempts.slice(1).every((a: {status: string}) => a.status === 'not_run')).toBe(true);
});

it('a real disk-write failure prevents the flow from being invoked', () => {
  const {directory, data, persist} = setupWriter();
  mkdirSync(join(directory, 'raw.json')); // Deliberately block the actual file write.
  const flow = vi.fn();
  expect(() => startPersistedAttempt(data.attempts[0], persist, flow)).toThrow();
  expect(flow).not.toHaveBeenCalled();
});

it('completion persistence replaces only the started slot and retains the other planned slots', () => {
  const {data, persist, read} = setupWriter(); persist();
  startPersistedAttempt(data.attempts[0], persist, () => {
    expect(read('summary').interrupted).toBe(1);
    Object.assign(data.attempts[0], {status: 'failed', failure_stage: 'setup', error: 'fixture failure', elapsed_ms: 5});
  });
  persist();
  expect(read('summary')).toMatchObject({attempted: 1, failed: 1, interrupted: 0, not_run: 19, valid: false});
  expect(read('raw').attempts[0].status).toBe('failed');
  expect(read('raw').environment).toEqual({kind: 'unit fixture'});
});
