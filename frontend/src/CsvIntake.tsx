import { useEffect, useRef, useState } from 'react';
import { previewCsv, type CsvPreview } from './api';
import type { Mutate } from './OfferDetail';
import type { Workspace } from './types';

export const CSV_MAX_BYTES = 65_536;
export const CSV_MAX_ROWS = 50;
export const CSV_SAMPLE = 'title,donor,quantity,unit,category,collection_date,use_by,allergens,allergens_unknown,hours_unrefrigerated,note\nSynthetic vegetables,Demonstration cooperative,120,kg,produce,2026-09-14,2026-09-16,,true,,Invented donation for community meals\n';

export function CsvIntake({ data, busy, mutate }: {data: Workspace; busy: boolean; mutate: Mutate}) {
  const [csv, setCsv] = useState('');
  const [review, setReview] = useState<CsvPreview>();
  const [selected, setSelected] = useState<number[]>([]);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const epoch = useRef(0);
  const controller = useRef<AbortController | undefined>(undefined);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => () => { epoch.current++; controller.current?.abort(); }, []);
  function cancel() {
    epoch.current++; controller.current?.abort();
    setCsv(''); setReview(undefined); setSelected([]); setPending(false);
    setMessage('Preview discarded. No offers were filed.');
    if (fileInput.current) fileInput.current.value = '';
  }
  async function read(file?: File) {
    if (!file || busy) return;
    const current = ++epoch.current;
    controller.current?.abort(); controller.current = new AbortController();
    setReview(undefined); setSelected([]); setCsv(''); setMessage(''); setPending(true);
    try {
      if (!/\.csv$/i.test(file.name)) throw new Error('Choose a .csv file exported as UTF-8.');
      if (file.size > CSV_MAX_BYTES) throw new Error(`CSV exceeds ${CSV_MAX_BYTES} bytes. Split the file.`);
      const content = await file.text();
      if (current !== epoch.current) return;
      const preview = await previewCsv(data, content, controller.current.signal);
      if (current !== epoch.current) return;
      setCsv(content); setReview(preview);
      setMessage('Preview only. Select each valid row you intend to file. No offers were filed.');
    } catch (error) {
      if (current === epoch.current) setMessage(error instanceof Error ? error.message : 'The CSV could not be read.');
    } finally { if (current === epoch.current) setPending(false); }
  }
  const stale = !!review && (review.version !== data.version || review.mode !== data.mode);
  const validSelection = review?.rows.filter(row => row.status === 'valid' && selected.includes(row.number)).map(row => row.number) || [];
  const disabled = busy || pending || stale || !data.can_write || !validSelection.length;
  return <section className="panel padded csv-intake" aria-label="Donor CSV intake">
    <h2>Preview a donor CSV</h2><p>{data.mode === 'sandbox' ? 'Use invented donations in this isolated sandbox.' : 'Live filing requires the existing authenticated coordinator grant.'} Preview validates rows without creating offers, starting the fleet or publishing records.</p>
    <details><summary>CSV schema and sample</summary><p>UTF-8, comma-separated, at most {CSV_MAX_BYTES.toLocaleString('en-US')} bytes and {CSV_MAX_ROWS} data rows. The header is case-sensitive. Quoted commas, escaped quotes and quoted newlines are supported.</p>
      <p>Required columns: <code>title, donor, quantity, unit, category, collection_date</code>. Optional: <code>use_by, allergens, allergens_unknown, hours_unrefrigerated, note</code>. No duplicate or extra columns.</p>
      <p>Quantity: above zero through 100,000, at most two decimals. Unit: kg or units. Category: ambient, chilled, frozen, produce or non-food. Dates: YYYY-MM-DD; use by cannot precede collection. Chilled/frozen food requires 0–168 hours unrefrigerated, at most one decimal. Declared allergens require allergens_unknown=false; otherwise use true or blank for unknown. Empty allergens stay unknown. Title/donor: 120 characters, allergens: 200, note: 600.</p>
      <p>No personal details or instructions to the checker. Formula-like cells beginning with =, +, - or @ are refused. Duplicate intake facts within the file or already in this workspace are skipped; different quantities, dates or food constraints are different donations.</p>
      <pre aria-label="CSV sample">{CSV_SAMPLE}</pre><p>Replace the example dates with the donor's actual dates. Copy this sample into a UTF-8 .csv file.</p>
    </details>
    <label>Donor CSV file<input ref={fileInput} type="file" accept=".csv,text/csv" disabled={busy || !data.can_write} aria-describedby={!data.can_write ? 'csv-write-reason' : busy ? 'csv-file-note' : undefined} onChange={e => void read(e.target.files?.[0])}/></label>
    {!data.can_write && <p className="notice" id="csv-write-reason">{data.authorization_note} Switch to Sandbox to preview and file invented donations.</p>}
    {pending && <p role="status">Validating the CSV. No offers are being filed.</p>}
    {message && <p role="status">{message}</p>}
    {stale && <p className="notice">Workspace changed since this preview. Choose the file again to recheck duplicates and clear the old selection.</p>}
    {review && <div className="csv-rows">{review.rows.map(row => <article key={row.number} className="csv-row" data-testid={`csv-row-${row.number}`}>
      <label className="check-label"><input type="checkbox" aria-label={`Select CSV row ${row.number}`} disabled={busy || stale || row.status !== 'valid'} aria-describedby={busy || stale || row.status !== 'valid' ? `csv-row-${row.number}-detail` : undefined} checked={selected.includes(row.number)} onChange={e => setSelected(previous => e.target.checked ? [...previous, row.number] : previous.filter(number => number !== row.number))}/>Row {row.number} · {row.status}</label>
      {row.offer && <><strong>{row.offer.title}</strong><p>{row.offer.donor} · {row.offer.quantity} {row.offer.unit} · {row.offer.category}</p><p>Collect {row.offer.collection_date} · use by {row.offer.use_by || 'unknown'} · allergens {row.offer.allergens?.join(', ') || 'unknown'}</p><details><summary>Review row {row.number} food constraints</summary><p>{row.offer.note || 'No donor note.'}</p><p>Hours unrefrigerated: {row.offer.hours_unrefrigerated ?? 'not applicable'}</p></details></>}
      <p id={`csv-row-${row.number}-detail`}>{row.detail}</p></article>)}</div>}
    <div className="form-actions"><button type="button" disabled={disabled} aria-describedby={disabled ? 'csv-file-reason' : undefined} onClick={() => {
      if (!disabled && review) void mutate('', 'import', {csv, csv_digest: review.digest, rows: validSelection});
    }}>File selected rows{validSelection.length ? ` (${validSelection.length})` : ''}</button><button type="button" className="secondary" disabled={busy} aria-describedby={busy ? 'csv-file-note' : undefined} onClick={cancel}>Cancel CSV preview</button></div>
    {disabled && <p className="small-note" id="csv-file-reason">{pending ? 'Available once the CSV check finishes.' : busy ? 'CSV filing is paused while the workspace saves, loads or needs a refresh.' : stale ? 'Available once you choose the file again.' : !data.can_write ? 'Unavailable in read-only records. Switch to your sandbox to file rows.' : 'Available once you select at least one valid row.'}</p>}
    <p className="small-note" id="csv-file-note">{busy ? 'CSV actions are paused while the workspace saves, loads or needs a refresh; cancellation cannot undo confirmed writes.' : 'Select valid rows explicitly before filing. Each row is revalidated through the existing governed intake API.'} Rows are filed one at a time. If filing stops, earlier confirmed rows remain; refresh and preview again to see duplicates. Filing does not approve food safety, an allocation or a pickup.</p>
  </section>;
}
