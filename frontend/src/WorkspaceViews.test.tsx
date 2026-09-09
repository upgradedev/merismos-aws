import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import * as api from './api';
import { App } from './App';
import { Dashboard, ActivityList } from './Dashboard';
import { DispatchWorkspace } from './DispatchWorkspace';
import { Records } from './Records';
import { OfferDetail } from './OfferDetail';
import { History, PickupCard } from './Pickups';
import { parseRoute } from './routes';
import { workspace } from './test/fixtures';

vi.mock('./api', async original => ({ ...await original<typeof api>(), loadWorkspace: vi.fn(), action: vi.fn() }));
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.loadWorkspace).mockResolvedValue(workspace()); vi.mocked(api.action).mockResolvedValue(workspace()); });
async function navigate(path: string) { await act(async () => { location.hash = path; window.dispatchEvent(new HashChangeEvent('hashchange')); }); }
const today = '2026-09-09';
function twoOffers() {
  const data = workspace(); data.offers.push({ ...structuredClone(data.offers[0]), offer: { ...data.offers[0].offer, id: 'offer-4483', title: 'Gift hampers', unit: 'units', quantity: 180 }, result: {}, plan: null, status: 'not_started' }); return data;
}
it('shows six truthful scoped metrics and drills into units and selected context', async () => {
  const data = twoOffers(); render(<Dashboard data={data} selected="offer-4471" today={today} unit="kg"/>);
  const cards = within(screen.getByRole('region', { name: 'Workspace metrics' }));
  expect(cards.getAllByRole('link')).toHaveLength(6);
  expect(cards.getByRole('link', { name: /Offered/ })).toHaveTextContent('240 kg');
  expect(cards.getByRole('link', { name: /Pending pickups/ })).toHaveAttribute('href', '#/records?offer=offer-4471&filter=pending&unit=kg');
  await userEvent.selectOptions(screen.getByLabelText('Metric unit'), 'units'); expect(location.hash).toBe('#/dashboard?offer=offer-4471&unit=units');
});
it('renders unknown, empty, live and conflict scopes without invented recent activity', () => {
  const data = twoOffers(); const { rerender } = render(<Dashboard data={data} selected="" today={today} unit="units"/>);
  expect(screen.getAllByText('Unknown')).toHaveLength(2);
  data.offers.push({ ...structuredClone(data.offers[0]), status: 'failed' }); data.mode = 'live';
  rerender(<Dashboard data={data} selected="" today={today} unit="units"/>); expect(screen.getByText(/conflicting identities were withheld/)).toBeVisible();
  data.offers = []; rerender(<Dashboard data={data} selected="" today={today} unit=""/>);
  expect(screen.getByText('No priority offers')).toBeVisible(); expect(screen.getByText('No unit available')).toBeInTheDocument();
});
it('renders dated and undated activity and historical addresses without inventing dates', () => {
  const data = workspace(); data.records = [{ key: 'record', offer_id: 'offer-4471', run_id: 'run', content_digest: 'digest', published_at: 1, superseded_by: '', mode: 'sandbox' }];
  data.pickups = [{ offer_id: 'offer-4471', title: 'Bread', org: 'Kitchen', quantity: 96, unit: 'kg', role: 'duty manager', state: 'confirmed', agreed_at: '', plan_digest: 'digest', run_id: 'run', confirmed_at: null }];
  const { rerender } = render(<ActivityList data={data}/>); expect(screen.getByText('Event time unavailable')).toBeVisible(); expect(document.querySelector('time')).toHaveAttribute('datetime', '1970-01-01T00:00:01.000Z');
  data.records[0].published_at = NaN; rerender(<History data={data} selected="offer-4471"/>); expect(screen.getByText('Publication time unavailable')).toBeVisible();
  data.pickups[0].confirmed_at = 2; rerender(<PickupCard item={data.pickups[0]} data={data} busy={false} mutate={vi.fn()} today={today}/>); expect(document.querySelector('time[datetime="1970-01-01T00:00:02.000Z"]')).toBeInTheDocument();
});
it('search preserves typing focus and URL selection while page navigation moves focus once', async () => {
  location.hash = '/workspace?offer=offer-4471'; render(<App/>); await screen.findByRole('heading', { name: 'Bread and vegetables' });
  await navigate('/records?offer=offer-4471'); expect(screen.getByRole('heading', { name: 'Records' })).toHaveFocus();
  const input = screen.getByRole('searchbox'); await userEvent.type(input, 'Bread');
  expect(input).toHaveValue('Bread'); expect(input).toHaveFocus(); expect(location.hash).toContain('q=Bread'); expect(location.hash).toContain('offer=offer-4471');
  await navigate('/records?offer=offer-4471&q=Bre'); expect(input).toHaveValue('Bre'); expect(input).toHaveFocus();
  await navigate('/history?offer=offer-4471'); expect(screen.getByRole('heading', { name: 'Sandbox history' })).toHaveFocus();
  expect(screen.getByRole('link', { name: 'Return to workspace →' })).toHaveAttribute('href', '#/workspace?offer=offer-4471');
});
it('records filters are URL-backed and empty/unknown results remain reviewable', async () => {
  const data = twoOffers(); const { rerender } = render(<Records data={data} route={parseRoute('/records?unit=units')} selected="offer-4483" today={today}/>);
  expect(screen.getAllByText('Unknown')).toHaveLength(2);
  await userEvent.selectOptions(screen.getByLabelText('Record filter'), 'pending'); expect(location.hash).toContain('filter=pending');
  await userEvent.selectOptions(screen.getByLabelText('Unit'), 'kg'); expect(location.hash).toContain('unit=kg');
  rerender(<Records data={data} route={parseRoute('/records?filter=pending')} selected="offer-4483" today={today}/>); expect(screen.getByText('No records match')).toBeVisible();
});
it('offer or exact-plan changes clear approval consent, including return to the previous offer', async () => {
  const data = twoOffers(); vi.mocked(api.loadWorkspace).mockResolvedValue(data); location.hash = '/workspace?offer=offer-4471'; render(<App/>);
  const consent = await screen.findByLabelText(/I have reviewed this exact allocation/); await userEvent.click(consent);
  await navigate('/workspace?offer=offer-4483'); expect(screen.queryByRole('checkbox')).not.toBeInTheDocument(); expect(screen.getByText(/No pickup is authorised/)).toBeVisible();
  await navigate('/workspace?offer=offer-4471'); expect(screen.getByRole('checkbox')).not.toBeChecked();
  await userEvent.click(screen.getByRole('checkbox')); data.offers[0].plan!.digest = 'changed'; vi.mocked(api.loadWorkspace).mockResolvedValue(structuredClone(data));
  await userEvent.click(screen.getByText('Refresh workspace')); await waitFor(() => expect(screen.getByRole('checkbox')).not.toBeChecked());
  expect(api.action).not.toHaveBeenCalled();
});
it('hidden or conflicting selected evidence cannot expose actionable approval', async () => {
  const data = twoOffers(); const props = { data, selected: 'offer-4471', filter: 'all' as const, unit: '', today, busy: false, mutate: vi.fn() };
  const { rerender } = render(<DispatchWorkspace {...props}/>); await userEvent.type(screen.getByRole('searchbox'), 'hampers');
  expect(screen.getByText(/Show this offer's evidence before acting/)).toBeVisible(); expect(screen.queryByText('Approve in sandbox')).not.toBeInTheDocument();
  rerender(<DispatchWorkspace {...props} selected="missing"/>); expect(screen.getByText('Offer not found')).toBeVisible();
  data.offers.push({ ...structuredClone(data.offers[0]), status: 'failed' }); rerender(<DispatchWorkspace {...props}/>); expect(screen.getByText(/Conflicting source identities/)).toBeVisible();
});
it('empty workspace and unknown allocation do not expose an approval path', () => {
  const data = workspace(); data.offers = []; render(<DispatchWorkspace data={data} selected="" filter="all" unit="" today={today} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByText('No offers yet')).toBeVisible(); expect(screen.getByText('No offers match')).toBeVisible();
});
it('integrates selected pickups and resets role, schedule and confirmation across offer changes', async () => {
  const data = twoOffers(); data.offers[0].plan!.recorded = true;
  data.pickups = ['Kitchen', 'Shelter'].map(org => ({ offer_id: 'offer-4471', title: 'Bread', org, quantity: 20, unit: 'kg', role: 'duty manager', state: 'claimed', agreed_at: '', plan_digest: 'digest', run_id: 'run' }));
  const props = { data, selected: 'offer-4471', filter: 'all' as const, unit: '', today, busy: false, mutate: vi.fn() };
  const { rerender } = render(<DispatchWorkspace {...props}/>);
  const select = screen.getByLabelText('Pickup organisation'); await userEvent.selectOptions(select, JSON.stringify(['Shelter', 'digest']));
  await userEvent.click(screen.getByLabelText(/This collection actually happened/));
  fireEvent.change(screen.getByLabelText('Collection time (your local time)'), { target: { value: '2026-09-10T12:00' } });
  rerender(<DispatchWorkspace {...props} selected="offer-4483"/>); expect(screen.queryByLabelText('Pickup organisation')).not.toBeInTheDocument();
  rerender(<DispatchWorkspace {...props}/>); expect(screen.getByLabelText('Pickup organisation')).toHaveValue(JSON.stringify(['Kitchen', 'digest'])); expect(screen.getByLabelText(/This collection actually happened/)).not.toBeChecked(); expect(screen.getByLabelText('Collection time (your local time)')).toHaveValue('');
});
it('stale response cannot replace a newer workspace or silently reenable unsafe actions', async () => {
  let resolve!: (data: ReturnType<typeof workspace>) => void;
  vi.mocked(api.loadWorkspace).mockReturnValueOnce(new Promise(done => { resolve = done; }));
  render(<App/>); await userEvent.selectOptions(screen.getByLabelText('Workspace', { exact: true }), 'live'); await screen.findByRole('heading', { name: 'Dashboard' });
  const stale = workspace(); stale.network = 'STALE NETWORK'; await act(async () => resolve(stale)); expect(screen.queryByText(/STALE NETWORK/)).not.toBeInTheDocument();
});
it('keeps the same pickup when backend ordering changes after a claim, and withholds a missing selection', async () => {
  const data = workspace(); data.offers[0].plan!.recorded = true;
  data.pickups = ['Kitchen', 'Shelter'].map(org => ({ offer_id: 'offer-4471', title: 'Bread', org, quantity: 20, unit: 'kg', role: '', state: 'unclaimed', agreed_at: '', plan_digest: 'digest', run_id: 'run' }));
  const props = { data, selected: 'offer-4471', filter: 'all' as const, unit: '', today, busy: false, mutate: vi.fn() };
  const { rerender } = render(<DispatchWorkspace {...props}/>);
  expect(screen.getByLabelText('Pickup organisation')).toHaveValue(JSON.stringify(['Kitchen', 'digest']));
  data.pickups[0].state = 'claimed'; data.pickups.reverse(); rerender(<DispatchWorkspace {...props}/>);
  expect(screen.getByLabelText('Pickup organisation')).toHaveValue(JSON.stringify(['Kitchen', 'digest'])); expect(screen.getByText('Claimed', { exact: true })).toBeVisible();
  data.pickups = data.pickups.filter(p => p.org !== 'Kitchen'); rerender(<DispatchWorkspace {...props}/>);
  expect(screen.getByText(/selected pickup is unavailable/)).toBeVisible(); expect(screen.queryByText('Claim this share')).not.toBeInTheDocument();
});
it('guards duplicate form submits and direct submit without consent', async () => {
  const data = workspace(); const mutate = vi.fn(); render(<OfferDetail row={data.offers[0]} data={data} busy={false} mutate={mutate}/>);
  fireEvent.submit(screen.getByText('Approve in sandbox').closest('form')!); expect(mutate).not.toHaveBeenCalled();
});
it('allows corrected intake after known HTTP 400 without refreshing and assigns a new input-bound request', async () => {
  location.hash = '/offers/new'; vi.mocked(api.action).mockRejectedValueOnce(new api.ApiError('Remove the phone number', 400));
  render(<App/>); const submit = await screen.findByText('Add to sandbox');
  await userEvent.type(screen.getByLabelText('What is being donated?'), 'Courtyard vegetables');
  fireEvent.submit(submit.closest('form')!); expect(await screen.findByRole('alert')).toHaveTextContent('rejected intake was not saved');
  expect(submit).toBeEnabled(); expect(screen.getByLabelText('What is being donated?')).toHaveValue('Courtyard vegetables');
  await userEvent.type(screen.getByLabelText("Donor's food and collection note"), 'Collect in the evening');
  fireEvent.submit(submit.closest('form')!); await waitFor(() => expect(api.action).toHaveBeenCalledTimes(2));
  expect(api.loadWorkspace).toHaveBeenCalledTimes(1); expect(vi.mocked(api.action).mock.calls[0][4]).not.toBe(vi.mocked(api.action).mock.calls[1][4]);
});
it('locks repeated clicks immediately while one backend action is pending', async () => {
  let resolve!: (data: ReturnType<typeof workspace>) => void;
  vi.mocked(api.action).mockReturnValue(new Promise(done => { resolve = done; }));
  location.hash = '/workspace?offer=offer-4471'; render(<App/>); const run = await screen.findByText('Re-run the fleet');
  fireEvent.click(run); fireEvent.click(run); expect(api.action).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Refresh workspace')).toBeDisabled(); expect(screen.getByLabelText('Workspace', { exact: true })).toBeDisabled();
  await act(async () => resolve(workspace()));
});
