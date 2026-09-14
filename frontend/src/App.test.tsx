import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from './App';
import * as api from './api';
import { removePreference, writePreference } from './storage';
import { workspace } from './test/fixtures';
vi.mock('./api', async original => ({...await original<typeof api>(),loadWorkspace:vi.fn(),action:vi.fn(),startIsolatedWorkspace:vi.fn()}));
beforeEach(() => { vi.clearAllMocks(); removePreference('merismos.mode'); vi.mocked(api.loadWorkspace).mockResolvedValue(workspace()); vi.mocked(api.action).mockResolvedValue(workspace()); vi.mocked(api.startIsolatedWorkspace).mockResolvedValue(workspace()); });
async function navigate(path: string) { await act(async () => { location.hash=path; window.dispatchEvent(new HashChangeEvent('hashchange')); }); }
it('loads, navigates with durable URLs, switches mode and refreshes', async () => {
  const user=userEvent.setup(); render(<App/>); expect(screen.getByText(/Loading your coordinator/)).toBeVisible();
  await screen.findByRole('heading',{name:'Dashboard'});
  expect(screen.queryByRole('link',{name:/Legacy offer view/})).not.toBeInTheDocument();
  expect(document.querySelector('a[href*="execute-api"]')).toBeNull();
  expect(within(screen.getByRole('navigation',{name:'Main navigation'})).queryByRole('link',{name:/testbook|acceptance/i})).not.toBeInTheDocument();
  expect(document.querySelector('.sidebar a[href="/UAT.testbook.html"]')).toBeNull();
  await user.click(screen.getByText('Skip to main content')); expect(screen.getByRole('main')).toHaveFocus();
  await navigate('/pickups'); expect(screen.getByRole('heading',{name:'Pickups'})).toBeVisible(); expect(document.title).toContain('Pickups');
  await navigate('/history'); expect(screen.getByText('Sandbox history')).toBeVisible(); expect(document.title).toContain('History');
  await navigate('/offers/new'); expect(screen.getByRole('heading',{name:'Add an offer'})).toBeVisible();
  await navigate('/offers/offer-4471'); expect(screen.getByRole('heading',{name:'Bread and vegetables'})).toBeVisible();
  await navigate('/missing'); expect(screen.getByText('Page not found')).toBeVisible();
  await navigate(''); await screen.findByRole('heading',{name:'Dashboard'});
  await user.selectOptions(screen.getByLabelText('Workspace',{exact:true}),'live'); await waitFor(() => expect(api.loadWorkspace).toHaveBeenCalledWith('live'));
  await screen.findByRole('heading',{name:'Dashboard'}); await user.click(screen.getByText('Refresh workspace')); expect(api.loadWorkspace).toHaveBeenCalledTimes(3);
});
it('reports a failed request and recovers an expired sandbox', async () => {
  vi.mocked(api.loadWorkspace).mockRejectedValueOnce(new api.ApiError('Session expired',410));
  render(<App/>); expect(await screen.findByRole('alert')).toHaveTextContent('Session expired');
  await userEvent.click(screen.getByText('Start a new sandbox'));
  expect(api.startIsolatedWorkspace).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText('Create isolated workspace')); await screen.findByRole('heading',{name:'Dashboard'});
  expect(api.action).not.toHaveBeenCalled();
});
it('refreshes on ordinary failures and safely handles non-Error failures', async () => {
  vi.mocked(api.loadWorkspace).mockRejectedValueOnce('bad'); render(<App/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded');
  await userEvent.click(screen.getByText('Refresh and review')); await screen.findByRole('heading',{name:'Dashboard'});
});
it('does not automatically retry failed mutations and reuses the request id on explicit retry', async () => {
  location.hash='/offers/offer-4471'; vi.mocked(api.action).mockRejectedValueOnce(new Error('Connection lost'));
  render(<App/>); const button=await screen.findByText('Recalculate the split'); await userEvent.click(button);
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection lost'); expect(api.action).toHaveBeenCalledTimes(1);
  expect(button).toBeDisabled();
  await userEvent.click(screen.getByText('Refresh and review'));
  await waitFor(() => expect(button).toBeEnabled());
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.queryByText(/saved view may be stale/)).not.toBeInTheDocument();
  expect(api.action).toHaveBeenCalledTimes(1);
  expect(api.startIsolatedWorkspace).not.toHaveBeenCalled();
  await userEvent.click(button); await waitFor(() => expect(api.action).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.action).mock.calls[0][4]).toBe(vi.mocked(api.action).mock.calls[1][4]);
});
it('navigates to the newly filed offer only after backend success', async () => {
  location.hash='/offers/new'; const next=workspace(); next.offers.push({...structuredClone(next.offers[0]),offer:{...next.offers[0].offer,id:'offer-4484',title:'New donation'}});
  vi.mocked(api.action).mockResolvedValue(next); render(<App/>); await screen.findByText('Add to sandbox');
  fireEvent.submit(screen.getByText('Add to sandbox').closest('form')!);
  await waitFor(() => expect(location.hash).toBe('#/offers/offer-4484'));
});
it('polls only running work and ignores results from a previous mode', async () => {
  vi.useFakeTimers(); const running=workspace(); running.offers[0].status='running'; vi.mocked(api.loadWorkspace).mockResolvedValue(running);
  const {unmount}=render(<App/>); await act(async () => {});
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); }); expect(api.loadWorkspace).toHaveBeenCalledTimes(2);
  unmount(); await act(async () => { await vi.advanceTimersByTimeAsync(5000); }); expect(api.loadWorkspace).toHaveBeenCalledTimes(2); vi.useRealTimers();
});

it('keeps pending reads passive and explains unauthorized recovery', async () => {
  const pending = {...workspace(), mode: 'live' as const, can_write: false,
    operations: [{id: 'reserved-attempt', offer_id: 'offer-4471', action: 'approve', status: 'pending'}]};
  vi.mocked(api.loadWorkspace).mockResolvedValue(pending);
  render(<App/>);
  expect(await screen.findByText('Reconcile recorded outcome')).toBeDisabled();
  expect(screen.getByText(/Ask the coordinator to reconcile/)).toBeVisible();
  expect(screen.getByText('Reconcile recorded outcome')).toHaveAttribute('aria-describedby', screen.getByText(/Ask the coordinator to reconcile/).id);
  await userEvent.click(screen.getByText('Refresh workspace'));
  expect(api.action).not.toHaveBeenCalled();
});

it('recovers only the selected reserved operation on explicit coordinator action', async () => {
  const pending = {...workspace(), operations: [{id: 'reserved-attempt',
    offer_id: 'offer-4471', action: 'approve', status: 'pending'}]};
  vi.mocked(api.loadWorkspace).mockResolvedValue(pending);
  render(<App/>);
  await userEvent.click(await screen.findByText('Reconcile recorded outcome'));
  expect(api.action).toHaveBeenCalledWith(pending, 'offer-4471', 'recover',
    {operation_id: 'reserved-attempt'}, expect.any(String));
});

it.each(['resolve', 'reject'])('ignores a late previous-session %s without clearing current retry intent', async outcome => {
  location.hash = '/offers/offer-4471';
  let finish!: (value: ReturnType<typeof workspace>) => void;
  let fail!: (error: Error) => void;
  vi.mocked(api.loadWorkspace).mockImplementationOnce(() => new Promise((resolve, reject) => {
    finish = resolve; fail = reject;
  }));
  const live = {...workspace(), mode: 'live' as const};
  vi.mocked(api.loadWorkspace).mockResolvedValue(live);
  vi.mocked(api.action).mockRejectedValueOnce(new Error('Current attempt unknown'));
  const user = userEvent.setup();
  render(<App/>);
  await user.selectOptions(screen.getByLabelText('Workspace', {exact: true}), 'live');
  const run = await screen.findByText('Recalculate the split');
  await user.click(run);
  expect(await screen.findByRole('alert')).toHaveTextContent('Current attempt unknown');
  const id = vi.mocked(api.action).mock.calls[0][4];
  await act(async () => {
    if (outcome === 'resolve') finish({...workspace(), operations: [{
      id, offer_id: 'offer-4471', action: 'run', status: 'failed',
    }]});
    else fail(new Error('Obsolete session error'));
  });
  expect(screen.getByRole('alert')).toHaveTextContent('Current attempt unknown');
  expect(run).toBeDisabled();
  await user.click(screen.getByText('Refresh and review'));
  await waitFor(() => expect(run).toBeEnabled());
  await user.click(run);
  expect(vi.mocked(api.action).mock.calls[1][4]).toBe(id);
});

it('restarts only after explicit confirmation', async () => {
  render(<App/>); await screen.findByRole('heading',{name:'Dashboard'});
  fireEvent.click(screen.getByText('About this demo'));
  fireEvent.click(screen.getByText('Start over in a new sandbox'));
  fireEvent.click(screen.getByText('No, keep this sandbox'));
  expect(api.startIsolatedWorkspace).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Start over in a new sandbox'));
  fireEvent.click(screen.getByText('Yes, start fresh'));
  await waitFor(() => expect(api.startIsolatedWorkspace).toHaveBeenCalledTimes(1));
  await screen.findByText(/New isolated workspace ready/);
});

it('a completed sandbox Dashboard opens the footer restart confirmation and restarts only after Yes', async () => {
  const done = workspace(); done.offers[0].plan!.recorded = true; done.offers[0].status = 'recorded';
  vi.mocked(api.loadWorkspace).mockResolvedValue(done); render(<App/>);
  await userEvent.click(await screen.findByRole('button', {name: 'Start over with a fresh sample'}));
  const confirm = screen.getByRole('button', {name: 'Yes, start fresh'});
  expect(confirm).toHaveFocus(); expect((confirm.closest('details') as HTMLDetailsElement).open).toBe(true);
  expect(api.startIsolatedWorkspace).not.toHaveBeenCalled();
  await userEvent.click(confirm); await waitFor(() => expect(api.startIsolatedWorkspace).toHaveBeenCalledTimes(1));
  await screen.findByText(/New isolated workspace ready/);
});

it('shows why reconcile is paused while an error needs a refresh', async () => {
  const pending = {...workspace(), operations: [{id: 'reserved-attempt',
    offer_id: 'offer-4471', action: 'approve', status: 'pending'}]};
  vi.mocked(api.loadWorkspace).mockResolvedValue(pending);
  vi.mocked(api.action).mockRejectedValueOnce(new Error('Connection lost'));
  render(<App/>);
  const reconcile = await screen.findByText('Reconcile recorded outcome');
  fireEvent.click(reconcile);
  const reason = await screen.findByText('Reconcile paused while a change is saved or an error needs a refresh.');
  expect(reconcile).toBeDisabled();
  expect(reconcile).toHaveAttribute('aria-describedby', reason.id);
});

it.each([
  {path: '/landing', heading: /Fair food surplus allocation/},
  {path: '/journeys', heading: /How a donation moves through Merismos/},
  {path: '/architecture', heading: /AWS architecture/},
  {path: '/impact', heading: /Impact and limits/},
])('keeps $path free of forbidden claims', async ({path, heading}) => {
  render(<App/>); await screen.findByRole('heading',{name:'Dashboard'});
  await navigate(path);
  expect(screen.getByRole('heading',{level:1,name:heading})).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/Sklavenitis|Veneti|Vassilopoulos|Panteleimon|Homeless Shelter|Refugee Solidarity|Elderly Care|Youth Community|Gini|CO₂|Diverted|vs\. last week|Telemetry|Executive|👑|arbitrat|negotiat|real-time|tamper|HMAC|Object Lock|Graviton|Non-Repudiation|45 Minutes|Too Good/);
});

it('labels shared records read-only unless the loaded live workspace can write', async () => {
  writePreference('merismos.mode', 'live');
  vi.mocked(api.loadWorkspace).mockResolvedValue({...workspace(), mode: 'live' as const, can_write: false});
  render(<App/>); await screen.findByRole('heading',{name:'Dashboard'});
  expect(api.loadWorkspace).toHaveBeenCalledWith('live');
  expect(screen.getByText('Shared demo records · read-only · synthetic data')).toBeVisible();
  expect(screen.getByRole('option',{name:'Shared demo records'})).toBeInTheDocument();
  vi.mocked(api.loadWorkspace).mockResolvedValue({...workspace(), mode: 'live' as const, can_write: true});
  await userEvent.click(screen.getByText('Refresh workspace'));
  expect(await screen.findByText('Shared records · synthetic data · your approval publishes a public record')).toBeVisible();
  expect(screen.queryByText('Shared demo records · read-only · synthetic data')).not.toBeInTheDocument();
});
