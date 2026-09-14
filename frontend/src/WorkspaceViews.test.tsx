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
it('first visit keeps Start with this offer as the only primary action', () => {
  const data = twoOffers(); data.offers[0] = { ...data.offers[0], status: 'not_started', result: {}, plan: null };
  render(<Dashboard data={data} selected="" today={today} unit="kg"/>);
  const start = within(screen.getByRole('region', { name: 'Your next donation' }));
  expect(start.getByRole('heading', { name: 'Next offer: Bread and vegetables' })).toBeVisible();
  expect(start.getAllByRole('link').map(link => link.textContent)).toEqual(['Start with this offer →']);
  expect(start.getByRole('link', { name: 'Start with this offer →' })).toHaveAttribute('href', '#/workspace?offer=offer-4471');
  expect(start.queryByRole('button')).not.toBeInTheDocument();
});
it('returning visitor gets one Continue my work action that targets the next open decision', () => {
  const data = twoOffers(); data.offers[0].plan!.recorded = true; data.offers[0].status = 'recorded';
  data.pickups = [{ offer_id: 'offer-4471', title: 'Bread', org: 'Kitchen', quantity: 96, unit: 'kg', role: '', state: 'unclaimed', agreed_at: '', plan_digest: 'digest', run_id: 'run' }];
  const { rerender } = render(<Dashboard data={data} selected="offer-4471" today={today} unit="kg"/>);
  const start = within(screen.getByRole('region', { name: 'Your next donation' }));
  expect(start.getByRole('heading', { name: /^Next open decision: Gift hampers$/ })).toBeVisible();
  expect(start.getAllByRole('link').map(link => link.textContent)).toEqual(['Continue my work →']);
  expect(start.getByRole('link', { name: 'Continue my work →' })).toHaveAttribute('href', '#/workspace?offer=offer-4483');
  expect(start.getByText('1 of 2 donations recorded so far.')).toBeVisible(); expect(start.getByText(/Start by calculating a proposed allocation/)).toBeVisible();
  data.offers[1] = { ...data.offers[1], status: 'blocked' }; rerender(<Dashboard data={data} selected="" today={today} unit="kg"/>);
  expect(start.getByRole('heading', { name: 'Next open decision: Bread and vegetables' })).toBeVisible();
  expect(start.getByRole('link', { name: 'Continue my work →' })).toHaveAttribute('href', '#/workspace?offer=offer-4471'); expect(start.getByText(/The allocation is approved/)).toBeVisible();
  data.offers[0].plan!.recorded = false; data.can_write = false; rerender(<Dashboard data={data} selected="" today={today} unit="kg"/>);
  expect(start.getByRole('link', { name: 'Open the next decision →' })).toHaveAttribute('href', '#/workspace?offer=offer-4471'); expect(start.getByText(/A proposed allocation is ready/)).toBeVisible();
  expect(start.queryByRole('link', { name: /Start with this offer/ })).not.toBeInTheDocument();
});
it('completed sandbox says every donation is recorded and only opens the confirmed restart', async () => {
  const data = twoOffers(); const plan = { ...data.offers[0].plan!, recorded: true };
  data.offers = data.offers.map(row => ({ ...row, plan, status: 'recorded' })); const onStartOver = vi.fn();
  const { rerender } = render(<Dashboard data={data} selected="" today={today} unit="kg" onStartOver={onStartOver}/>);
  const start = within(screen.getByRole('region', { name: 'Your next donation' }));
  expect(start.getByRole('heading', { name: 'Every donation in this sandbox is recorded' })).toBeVisible();
  expect(start.getAllByRole('button').map(button => button.textContent)).toEqual(['Start over with a fresh sample']);
  expect(start.queryByRole('link', { name: /Start with this offer|Continue my work/ })).not.toBeInTheDocument();
  expect(start.getByRole('link', { name: 'History' })).toHaveAttribute('href', '#/history');
  await userEvent.click(start.getByRole('button', { name: 'Start over with a fresh sample' })); expect(onStartOver).toHaveBeenCalledTimes(1);
  data.offers[1] = { ...data.offers[1], plan: null, status: 'blocked' }; data.mode = 'live';
  rerender(<Dashboard data={data} selected="" today={today} unit="kg"/>);
  expect(start.getByRole('heading', { name: 'Every donation in these shared records is recorded or stopped with a reason' })).toBeVisible();
  expect(start.queryByRole('button')).not.toBeInTheDocument(); expect(start.getByRole('link', { name: 'Review the history →' })).toHaveAttribute('href', '#/history');
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
  await navigate('/workspace?offer=offer-4483'); expect(screen.queryByRole('checkbox')).not.toBeInTheDocument(); expect(screen.getByText('No allocation is approved for this offer, so there is no collection to record.')).toBeVisible(); expect(screen.queryByText(/collection is confirmed separately/)).not.toBeInTheDocument();
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
it('a blocked or refused offer with no allocation shows no approval sentence beside its pickups', () => {
  const data = workspace(); data.offers[0] = { ...data.offers[0], status: 'blocked', result: { run_id: 'run-refused', outcome: 'blocked', note: 'The cold chain is broken, so the offer is refused in full.' }, plan: null };
  render(<DispatchWorkspace data={data} selected="offer-4471" filter="all" unit="" today={today} busy={false} mutate={vi.fn()}/>);
  const tasks = within(screen.getByRole('region', { name: 'Selected offer pickups' }));
  expect(tasks.getByText('No allocation is approved for this offer, so there is no collection to record.')).toBeVisible();
  expect(tasks.queryByText(/until the exact allocation is approved|collection is confirmed separately/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Approve in sandbox' })).not.toBeInTheDocument(); expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
});
it('puts the skip button before the decision pane, the journey after it and the offer stream last', async () => {
  render(<DispatchWorkspace data={workspace()} selected="offer-4471" filter="all" unit="" today={today} busy={false} mutate={vi.fn()}/>);
  const pane = screen.getByRole('complementary', { name: 'Decision and dispatch' }); const skip = screen.getByRole('button', { name: 'Go to next decision ↓' });
  const journey = screen.getByRole('region', { name: 'Offer to pickup journey' }); const stream = screen.getByRole('region', { name: 'Intake and allocation' });
  const follows = (a: Element, b: Element) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
  expect(follows(skip, pane)).toBe(true); expect(follows(pane, journey)).toBe(true); expect(follows(journey, stream)).toBe(true);
  expect(within(pane).getByText('Approval records your decision; collection is confirmed separately.')).toBeVisible(); expect(within(pane).getByText('No pickup is authorised for this offer until the exact allocation is approved.')).toBeVisible();
  expect(follows(within(pane).getByRole('button', { name: 'Recalculate the split' }), within(pane).getAllByText('The gate passed. Approval is required.')[0])).toBe(true);
  await userEvent.click(skip); expect(pane).toHaveFocus();
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
it('keeps an exact pickup in navigation URLs and on remount, but clears it on offer change', async () => {
  const data = twoOffers(); data.offers[0].plan!.recorded = true;
  data.pickups = ['Kitchen', 'Shelter'].map(org => ({ offer_id: 'offer-4471', title: 'Bread', org, quantity: 20, unit: 'kg', role: 'duty manager', state: 'claimed', agreed_at: '', plan_digest: 'digest', run_id: 'run' }));
  vi.mocked(api.loadWorkspace).mockResolvedValue(data); location.hash = '/workspace?offer=offer-4471';
  const first = render(<App/>);
  await userEvent.selectOptions(await screen.findByLabelText('Pickup organisation'), JSON.stringify(['Shelter', 'digest']));
  expect(parseRoute(location.hash.slice(1)).pickup).toBe(JSON.stringify(['Shelter', 'digest']));
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByText('Dashboard'));
  await screen.findByRole('heading', { name: 'Dashboard' });
  await userEvent.click(screen.getByRole('link', { name: /^Pending pickups/ }));
  await screen.findByRole('heading', { name: /^Records$/ });
  await userEvent.click(screen.getByRole('link', { name: 'Return to workspace →' }));
  expect(await screen.findByLabelText('Pickup organisation')).toHaveValue(JSON.stringify(['Shelter', 'digest']));
  first.unmount(); render(<App/>);
  expect(await screen.findByLabelText('Pickup organisation')).toHaveValue(JSON.stringify(['Shelter', 'digest']));
  await navigate('/workspace?offer=offer-4483');
  expect(parseRoute(location.hash.slice(1)).pickup).toBe('');
  await navigate('/workspace?offer=offer-4471');
  expect(await screen.findByLabelText('Pickup organisation')).toHaveValue(JSON.stringify(['Kitchen', 'digest']));
  expect(screen.getByLabelText(/This collection actually happened/)).not.toBeChecked();
});
it('does not fall back to another organisation for an unavailable pickup deep link', async () => {
  const data = workspace(); data.offers[0].plan!.recorded = true;
  data.pickups = [{ offer_id: 'offer-4471', title: 'Bread', org: 'Kitchen', quantity: 20, unit: 'kg', role: '', state: 'unclaimed', agreed_at: '', plan_digest: 'digest', run_id: 'run' }];
  vi.mocked(api.loadWorkspace).mockResolvedValue(data);
  location.hash = '/workspace?offer=offer-4471&pickup=missing'; render(<App/>);
  expect(await screen.findByText(/selected pickup is unavailable/)).toBeVisible();
  expect(screen.queryByText('Claim this share')).not.toBeInTheDocument();
  expect(api.action).not.toHaveBeenCalled();
});
it('allows corrected intake after known HTTP 400 without refreshing and assigns a new input-bound request', async () => {
  location.hash = '/offers/new'; vi.mocked(api.action).mockRejectedValueOnce(new api.ApiError('Remove the phone number', 400));
  render(<App/>); const submit = await screen.findByText('Add to sandbox');
  await userEvent.type(screen.getByLabelText('What is being donated?'), 'Courtyard vegetables');
  fireEvent.change(screen.getByLabelText("Donor's food and collection note"), { target: { value: 'Call 6941234567' } });
  fireEvent.submit(submit.closest('form')!); expect(await screen.findByRole('alert')).toHaveTextContent('rejected intake was not saved'); expect(screen.getAllByRole('alert')).toHaveLength(1); expect(screen.getByLabelText("Donor's food and collection note")).toHaveAttribute('aria-invalid','true');
  expect(submit).toBeEnabled(); expect(screen.getByLabelText('What is being donated?')).toHaveValue('Courtyard vegetables');
  await userEvent.clear(screen.getByLabelText("Donor's food and collection note")); await userEvent.type(screen.getByLabelText("Donor's food and collection note"), 'Collect in the evening');
  fireEvent.submit(submit.closest('form')!); await waitFor(() => expect(api.action).toHaveBeenCalledTimes(2));
  expect(api.loadWorkspace).toHaveBeenCalledTimes(1); expect(vi.mocked(api.action).mock.calls[0][4]).not.toBe(vi.mocked(api.action).mock.calls[1][4]);
});
it('keeps one refused-intake alert, without a marked field, when the coordinator leaves the form', async () => {
  location.hash = '/offers/new'; vi.mocked(api.action).mockRejectedValueOnce(new api.ApiError('This donation is already filed as offer-88.', 400));
  render(<App/>); const submit = await screen.findByText('Add to sandbox');
  fireEvent.submit(submit.closest('form')!); expect(await screen.findByRole('alert')).toHaveTextContent('Check the form');
  expect(screen.getByLabelText("Donor's food and collection note")).not.toHaveAttribute('aria-invalid');
  await navigate('/dashboard'); expect(screen.getAllByRole('alert')).toHaveLength(1);
  expect(screen.getByRole('alert')).toHaveTextContent('That action could not be completed');
});
it('locks repeated clicks immediately while one backend action is pending', async () => {
  let resolve!: (data: ReturnType<typeof workspace>) => void;
  vi.mocked(api.action).mockReturnValue(new Promise(done => { resolve = done; }));
  location.hash = '/workspace?offer=offer-4471'; render(<App/>); const run = await screen.findByText('Recalculate the split');
  fireEvent.click(run); fireEvent.click(run); expect(api.action).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Refresh workspace')).toBeDisabled(); expect(screen.getByLabelText('Workspace', { exact: true })).toBeDisabled();
  await act(async () => resolve(workspace()));
});
