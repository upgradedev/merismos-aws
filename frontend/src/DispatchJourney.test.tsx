import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { decisionRows, DispatchJourney, DisruptionControl, downloadManifest, ManifestExport, pickupManifest, ReplanComparison } from './DispatchJourney';
import { workspace } from './test/fixtures';

function changed() {
  const data = workspace(); const row = data.offers[0];
  row.replan = {org: 'Omonoia Soup Kitchen', capacity: 0, unit: 'kg', previous_quantity: 96,
    before: structuredClone(row.result), before_digest: 'old-digest', before_recorded: true,
    before_key: 'records/original.md', source: 'offers/offer-4471.json'};
  row.result = {...row.result, draft_allocations: [{org: 'Elpida Night Shelter', quantity: 20, reason: 'Collection capacity limit 20 kg.', share_of_offer: 20 / 240}], draft_barred_because: {'Omonoia Soup Kitchen': 'Collection capacity is zero kg.'}};
  return data;
}
it('compares all actual recipients and exclusions without inventing a current allocation', () => {
  const data = changed(); const row = data.offers[0];
  const rows = decisionRows(row.replan!.before, row.result, true);
  expect(rows.find(r => r.org === 'Omonoia Soup Kitchen')?.after).toContain('capacity is zero');
  expect(rows.find(r => r.org === 'Elpida Night Shelter')?.before).toBe('No decision reported');
  expect(decisionRows(row.replan!.before, {}, false).every(r => r.after.startsWith('Replan required'))).toBe(true);
  const view = render(<ReplanComparison row={row}/>);
  expect(screen.getByText(/Fresh exact-plan approval is required/)).toBeVisible();
  row.plan!.recorded = true; view.rerender(<ReplanComparison row={row}/>);
  expect(screen.getByText(/new exact plan is approved/)).toBeVisible();
  row.plan = null; view.rerender(<ReplanComparison row={row}/>);
  expect(screen.getByText(/Old allocation is no longer actionable/)).toBeVisible();
  view.rerender(<ReplanComparison row={{...row, replan: undefined}}/>);
  expect(screen.queryByText('What changed and why')).not.toBeInTheDocument();
});
it('exports original identity, before/after, current commitments and limitations as inert text', async () => {
  const data = changed(); const row = data.offers[0]; row.offer.title = '=HYPERLINK("bad")';
  data.pickups = [{offer_id: row.offer.id, title: 'Donation', org: 'Kitchen', quantity: 96, unit: 'kg', role: '', state: 'invalidated', agreed_at: '', plan_digest: 'current', commitment_digest: 'old-digest', run_id: 'old-run'}];
  const text = pickupManifest(row, data);
  expect(text).toContain('=HYPERLINK'); expect(text).toContain('old-digest');
  expect(text).toContain('invalidated'); expect(text).toContain('not universal or certified fairness');
  expect(text).toContain('Human/coordinator proof NOT_RUN'); expect(text).toContain('not measured');
  const user = userEvent.setup();
  const write = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {value: {writeText: write}, configurable: true});
  render(<ManifestExport row={row} data={data}/>);
  await user.click(screen.getByText('Pickup manifest · copy or download'));
  await user.click(screen.getByText('Copy pickup manifest'));
  expect(write).toHaveBeenCalledWith(text);
  expect(screen.getByRole('status')).toHaveTextContent('No message was sent');
  write.mockRejectedValueOnce(new Error('denied'));
  await user.click(screen.getByText('Copy pickup manifest'));
  expect(screen.getByRole('status')).toHaveTextContent('Select and copy');
  expect(screen.getByLabelText('Pickup manifest')).toHaveValue(text);
});
it('a completed zero-allocation replan reports actual exclusions, not a pending computation', () => {
  const data = changed(); const row = data.offers[0]; row.plan = null;
  row.status = 'nothing_to_allocate'; row.result.outcome = 'nothing_to_allocate';
  row.result.draft_allocations = [];
  render(<><ReplanComparison row={row}/><DispatchJourney row={row} data={data}/></>);
  expect(screen.getByText(/Replan completed with no feasible allocation/)).toBeVisible();
  expect(screen.getByText('No feasible allocation')).toBeVisible();
  expect(pickupManifest(row, data)).toContain('after 0: Collection capacity is zero');
});
it('download uses text/plain and a fixed txt name, never CSV/HTML or a data-provided address', async () => {
  const create = vi.fn().mockReturnValue('blob:manifest');
  const revoke = vi.fn();
  Object.defineProperty(URL, 'createObjectURL', {value: create, configurable: true});
  Object.defineProperty(URL, 'revokeObjectURL', {value: revoke, configurable: true});
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function(this: HTMLAnchorElement) {
    expect(this.download).toBe('merismos-pickup-manifest.txt'); expect(this.href).toBe('blob:manifest');
  });
  downloadManifest('<script>alert(1)</script>');
  expect(create.mock.calls[0][0].type).toBe('text/plain;charset=utf-8');
  await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:manifest'));
  const data = workspace(); render(<ManifestExport row={data.offers[0]} data={data}/>);
  await userEvent.click(screen.getByText('Pickup manifest · copy or download'));
  await userEvent.click(screen.getByText('Download pickup manifest'));
  expect(screen.getByRole('status')).toHaveTextContent('downloaded as plain text');
  create.mockImplementationOnce(() => {throw new Error('denied');});
  await userEvent.click(screen.getByText('Download pickup manifest'));
  expect(screen.getByRole('status')).toHaveTextContent('Download unavailable'); click.mockRestore();
});
it('requires lower unit-correct capacity and binds the simulated change to the exact prior plan', async () => {
  const data = workspace(); const row = data.offers[0]; const mutate = vi.fn();
  render(<DisruptionControl row={row} data={data} busy={false} mutate={mutate}/>);
  await userEvent.click(screen.getByText('Rehearse a collection disruption'));
  const capacity = screen.getByLabelText('New collection capacity (kg)');
  fireEvent.change(capacity, {target: {value: '96'}});
  expect(screen.getByText('Record simulated disruption')).toBeDisabled();
  fireEvent.submit(capacity.closest('form')!); expect(mutate).not.toHaveBeenCalled();
  fireEvent.change(capacity, {target: {value: '0.29'}});
  await userEvent.click(screen.getByText('Record simulated disruption'));
  expect(mutate).toHaveBeenCalledWith(row.offer.id, 'disrupt', {org: 'Omonoia Soup Kitchen', capacity: 0.29, consent: true, digest: row.plan!.digest, run_id: row.plan!.run_id});
});
it('disruption control explains live, no-plan, confirmed and busy boundaries', async () => {
  const data = workspace(); const row = data.offers[0]; const props = {row, data, busy: false, mutate: vi.fn()};
  const view = render(<DisruptionControl {...props} data={{...data, mode: 'live'}}/>);
  await userEvent.click(screen.getByText('Rehearse a collection disruption'));
  expect(screen.getByText(/live source records cannot be edited/)).toBeVisible();
  view.rerender(<DisruptionControl {...props} row={{...row, plan: null}}/>);
  expect(screen.getByText(/computed plan is required/)).toBeVisible();
  view.rerender(<DisruptionControl {...props} data={{...data, pickups: [{offer_id: row.offer.id, state: 'confirmed'} as typeof data.pickups[number]]}}/>);
  expect(screen.getByText(/Collection is already confirmed/)).toBeVisible();
  view.rerender(<DisruptionControl {...props} busy/>);
  expect(screen.getByText('Record simulated disruption')).toBeDisabled();
});
it('journey and manifest keep unknown, draft, replan and recorded states distinct', () => {
  const data = workspace(); const row = data.offers[0];
  const view = render(<DispatchJourney row={{...row, plan: null}} data={data}/>);
  expect(screen.getByText('Needs review')).toBeVisible();
  expect(pickupManifest({...row, result: {}, plan: null, status: 'not_started'}, data)).toContain('Allocated: unknown');
  const next = changed(); view.rerender(<DispatchJourney row={next.offers[0]} data={next}/>);
  expect(screen.getByText('Fresh approval required')).toBeVisible();
  next.offers[0].plan!.recorded = true;
  view.rerender(<DispatchJourney row={next.offers[0]} data={next}/>);
  expect(screen.getByText('Approved in sandbox')).toBeVisible();
  expect(pickupManifest(next.offers[0], next)).toContain('Allocation recorded by the server');
});
