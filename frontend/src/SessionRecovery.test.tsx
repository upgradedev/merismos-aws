import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { SessionRecovery } from './SessionRecovery';

it('requires a reviewable restart choice and lets the user keep the previous context', async () => {
  const refresh = vi.fn(), restart = vi.fn(); const user = userEvent.setup();
  render(<SessionRecovery message="Session unavailable" sessionUnavailable mode="sandbox" busy={false} hasSnapshot refresh={refresh} restart={restart}/>);
  expect(screen.getByRole('alert')).toHaveTextContent('expired, be unknown or have had access revoked');
  expect(screen.getByRole('alert')).toHaveTextContent('last loaded offer');
  await user.click(screen.getByText('Start a new sandbox'));
  expect(restart).not.toHaveBeenCalled();
  await user.click(screen.getByText('Keep previous workspace'));
  expect(restart).not.toHaveBeenCalled();
  await user.click(screen.getByText('Refresh and review')); expect(refresh).toHaveBeenCalledOnce();
  await user.click(screen.getByText('Start a new sandbox'));
  await user.click(screen.getByText('Create isolated workspace')); expect(restart).toHaveBeenCalledOnce();
});
it('never offers a live identity change and disables recovery while a request is running', async () => {
  const props = {message: 'Access refused', sessionUnavailable: true, busy: true, hasSnapshot: false, refresh: vi.fn(), restart: vi.fn()};
  const view = render(<SessionRecovery {...props} mode="live"/>);
  expect(screen.queryByText('Start a new sandbox')).not.toBeInTheDocument();
  expect(screen.getByText('Refresh and review')).toBeDisabled();
  expect(screen.getByText('Paused while the workspace refreshes.')).toBeVisible();
  view.rerender(<SessionRecovery {...props} sessionUnavailable={false} mode="sandbox"/>);
  expect(screen.getByText('Start a separate sandbox')).toBeDisabled();
  expect(screen.getByRole('alert')).toHaveTextContent('does not repeat an approval');
});
