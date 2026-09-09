import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from './App';
import * as api from './api';
import { removePreference } from './storage';
import { workspace } from './test/fixtures';
vi.mock('./api', async original => ({...await original<typeof api>(),loadWorkspace:vi.fn(),action:vi.fn()}));
beforeEach(() => { vi.clearAllMocks(); removePreference('merismos.mode'); vi.mocked(api.loadWorkspace).mockResolvedValue(workspace()); vi.mocked(api.action).mockResolvedValue(workspace()); });
async function navigate(path: string) { await act(async () => { location.hash=path; window.dispatchEvent(new HashChangeEvent('hashchange')); }); }
it('loads, navigates with durable URLs, switches mode and refreshes', async () => {
  const user=userEvent.setup(); render(<App/>); expect(screen.getByText(/Loading your coordinator/)).toBeVisible();
  await screen.findByRole('heading',{name:'Dashboard'});
  const legacy = screen.getByRole('link',{name:'Legacy offer view ↗'});
  expect(legacy).toHaveAttribute('href','https://efnt6e0kv7.execute-api.eu-west-1.amazonaws.com/offer/offer-4471');
  expect(legacy).toHaveAttribute('target','_blank'); expect(legacy).toHaveAttribute('rel','noreferrer');
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
  await userEvent.click(screen.getByText('Start a new sandbox')); await screen.findByRole('heading',{name:'Dashboard'});
});
it('refreshes on ordinary failures and safely handles non-Error failures', async () => {
  vi.mocked(api.loadWorkspace).mockRejectedValueOnce('bad'); render(<App/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded');
  await userEvent.click(screen.getByText('Refresh and review')); await screen.findByRole('heading',{name:'Dashboard'});
});
it('does not automatically retry failed mutations and reuses the request id on explicit retry', async () => {
  location.hash='/offers/offer-4471'; vi.mocked(api.action).mockRejectedValueOnce(new Error('Connection lost'));
  render(<App/>); const button=await screen.findByText('Re-run the fleet'); await userEvent.click(button);
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection lost'); expect(api.action).toHaveBeenCalledTimes(1);
  expect(button).toBeDisabled();
  await userEvent.click(screen.getByText('Refresh and review'));
  await waitFor(() => expect(button).toBeEnabled());
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
