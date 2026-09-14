import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import * as api from './api';
import { CsvIntake, CSV_MAX_BYTES, CSV_SAMPLE } from './CsvIntake';
import { workspace } from './test/fixtures';

vi.mock('./api', async original => ({...await original<typeof api>(), previewCsv: vi.fn()}));
const review = (): api.CsvPreview => ({digest: 'csv-digest', version: 1, mode: 'sandbox', max_bytes: CSV_MAX_BYTES, max_rows: 50, rows: [
  {number: 2, status: 'valid', detail: 'Valid intake; not a safety approval.', offer: workspace().offers[0].offer},
  {number: 3, status: 'invalid', detail: 'quantity: a value is required.', offer: null},
  {number: 4, status: 'duplicate', detail: 'Already filed as offer-88.', offer: null},
]});
function file(name = 'donors.csv', text = CSV_SAMPLE) {
  const value = new File([text], name, {type: 'text/csv'});
  Object.defineProperty(value, 'text', {value: vi.fn().mockResolvedValue(text)});
  return value;
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.previewCsv).mockResolvedValue(review()); });
it('reviews without mutation and commits only deliberately selected valid rows', async () => {
  const mutate = vi.fn(); render(<CsvIntake data={workspace()} busy={false} mutate={mutate}/>);
  expect(screen.getByText('File selected rows')).toBeDisabled(); expect(screen.getByText('Available once you select at least one valid row.')).toBeVisible();
  await userEvent.click(screen.getByText('CSV schema and sample'));
  expect(screen.getByLabelText('CSV sample')).toHaveTextContent('collection_date');
  await userEvent.upload(screen.getByLabelText('Donor CSV file'), file());
  await screen.findByText('Already filed as offer-88.');
  expect(api.previewCsv).toHaveBeenCalledWith(expect.anything(), CSV_SAMPLE, expect.any(AbortSignal));
  expect(mutate).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Select CSV row 3')).toBeDisabled();
  expect(screen.getByLabelText('Select CSV row 4')).toBeDisabled();
  expect(screen.getByLabelText('Select CSV row 3')).toHaveAttribute('aria-describedby', 'csv-row-3-detail');
  const select = screen.getByLabelText('Select CSV row 2');
  expect(select).not.toHaveAttribute('aria-describedby');
  expect(select).not.toBeChecked(); await userEvent.click(select); await userEvent.click(select);
  expect(screen.getByText('File selected rows')).toBeDisabled();
  await userEvent.click(select); await userEvent.click(screen.getByText('File selected rows (1)'));
  expect(mutate).toHaveBeenCalledWith('', 'import', {csv: CSV_SAMPLE, csv_digest: 'csv-digest', rows: [2]});
  await userEvent.click(screen.getByText('Review row 2 food constraints'));
  expect(screen.getByText(/Hours unrefrigerated: not applicable/)).toBeVisible();
});
it('cancel discards bytes and selection without writing or allowing an old response to restore them', async () => {
  let resolve!: (value: api.CsvPreview) => void;
  vi.mocked(api.previewCsv).mockReturnValue(new Promise(done => {resolve = done;}));
  const mutate = vi.fn(); render(<CsvIntake data={workspace()} busy={false} mutate={mutate}/>);
  await userEvent.upload(screen.getByLabelText('Donor CSV file'), file());
  await waitFor(() => expect(api.previewCsv).toHaveBeenCalled());
  const signal = vi.mocked(api.previewCsv).mock.calls[0][2];
  await userEvent.click(screen.getByText('Cancel CSV preview')); expect(signal.aborted).toBe(true);
  await act(async () => resolve(review()));
  expect(screen.queryByLabelText('Select CSV row 2')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('No offers were filed');
  expect(mutate).not.toHaveBeenCalled();
});
it('stale workspace, busy import and live authorization withhold commit', async () => {
  const data = workspace(); const mutate = vi.fn();
  const {rerender} = render(<CsvIntake data={data} busy={false} mutate={mutate}/>);
  await userEvent.upload(screen.getByLabelText('Donor CSV file'), file());
  await userEvent.click(await screen.findByLabelText('Select CSV row 2'));
  rerender(<CsvIntake data={{...data, version: 2}} busy={false} mutate={mutate}/>);
  const staleReason = screen.getByText(/Workspace changed since this preview/);
  expect(staleReason).toBeVisible(); expect(staleReason).toHaveAttribute('id', 'csv-stale-reason');
  expect(screen.getByText('File selected rows (1)')).toBeDisabled();
  expect(screen.getByLabelText('Select CSV row 2')).toHaveAttribute('aria-describedby', 'csv-stale-reason');
  expect(screen.getByLabelText('Select CSV row 3')).toHaveAttribute('aria-describedby', 'csv-stale-reason csv-row-3-detail');
  rerender(<CsvIntake data={data} busy mutate={mutate}/>);
  expect(screen.getByLabelText('Select CSV row 2')).toBeDisabled();
  expect(screen.getByLabelText('Select CSV row 2')).toHaveAttribute('aria-describedby', 'csv-file-note');
  expect(screen.getByLabelText('Select CSV row 4')).toHaveAttribute('aria-describedby', 'csv-file-note csv-row-4-detail');
  expect(document.getElementById('csv-file-note')).toHaveTextContent(/CSV actions are paused/);
  expect(screen.getByText('Cancel CSV preview')).toBeDisabled();
  expect(screen.getByText('CSV filing is paused while the workspace saves, loads or needs a refresh.')).toBeVisible();
  expect(screen.getByText('Cancel CSV preview')).toHaveAttribute('aria-describedby', 'csv-file-note');
  expect(screen.getByText(/CSV actions are paused while the workspace saves, loads or needs a refresh/)).toBeVisible();
  rerender(<CsvIntake data={{...data, mode: 'live', can_write: false}} busy={false} mutate={mutate}/>);
  expect(screen.getByLabelText('Donor CSV file')).toBeDisabled();
  expect(screen.getByText(/Switch to Sandbox to preview/)).toBeVisible();
  expect(mutate).not.toHaveBeenCalled();
});
it.each(['donors.xlsx', 'too-big.csv', 'unreadable.csv', 'refused.csv'])('refuses %s without persisting input', async name => {
  const input = file(name, name === 'too-big.csv' ? 'x'.repeat(CSV_MAX_BYTES + 1) : CSV_SAMPLE);
  if (name === 'unreadable.csv') vi.mocked(input.text).mockRejectedValue(new Error('Cannot read file'));
  if (name === 'refused.csv') vi.mocked(api.previewCsv).mockRejectedValue(new Error('Malformed CSV'));
  render(<CsvIntake data={workspace()} busy={false} mutate={vi.fn()}/>);
  fireEvent.change(screen.getByLabelText('Donor CSV file'), {target: {files: [input]}});
  await waitFor(() => expect(screen.getByRole('status')).not.toHaveTextContent('Validating'));
  expect(screen.getByText('File selected rows')).toBeDisabled();
  expect(screen.queryByLabelText('Select CSV row 2')).not.toBeInTheDocument();
});
it('a new file supersedes a pending read and unmount aborts its preview', async () => {
  const slow = file(); let resolve!: (value: string) => void;
  vi.mocked(slow.text).mockReturnValue(new Promise(done => {resolve = done;}));
  const view = render(<CsvIntake data={workspace()} busy={false} mutate={vi.fn()}/>);
  await userEvent.upload(screen.getByLabelText('Donor CSV file'), slow);
  expect(screen.getByText('Available once the CSV check finishes.')).toBeVisible();
  await userEvent.click(screen.getByText('Cancel CSV preview'));
  await act(async () => resolve(CSV_SAMPLE)); expect(api.previewCsv).not.toHaveBeenCalled();
  await userEvent.upload(screen.getByLabelText('Donor CSV file'), file('second.csv'));
  await screen.findByLabelText('Select CSV row 2');
  view.unmount(); expect(vi.mocked(api.previewCsv).mock.calls[0][2].aborted).toBe(true);
});
it('explains why filing and file choice are unavailable in read-only records', () => {
  render(<CsvIntake data={{...workspace(), mode: 'live', can_write: false}} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByText('Unavailable in read-only records. Switch to your sandbox to file rows.')).toBeVisible();
  expect(screen.getByText('File selected rows')).toHaveAttribute('aria-describedby', 'csv-file-reason');
  expect(screen.getByLabelText('Donor CSV file')).toHaveAttribute('aria-describedby', 'csv-write-reason');
});
