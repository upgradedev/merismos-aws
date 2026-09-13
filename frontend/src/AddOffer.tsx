import { useEffect, useRef, useState } from 'react';
import type { Mutate } from './OfferDetail';
import type { Workspace } from './types';
import { CsvIntake } from './CsvIntake';

const examples = {
  success: { title: 'Synthetic courtyard vegetables', category: 'ambient', note: 'Invented produce for same-day community meals.' },
  refusal: { title: 'Synthetic chilled food', category: 'chilled', note: 'Invented cold-chain break. This should require a safety refusal.' },
  correction: { title: 'Synthetic corrected donation', category: 'ambient', note: 'Call 6941234567' },
};

export type IntakeValues = { title: string; donor: string; note: string };

// The backend refuses personal data in the title, donor or note with one message
// that never names the field. These mirror the patterns in src/merismos/gate.py, and
// the backend checks title, donor and note in that order, so the first submitted
// field that matches is the one it refused. No match marks nothing.
const personShapes = [
  /\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}\s?[A-Z0-9]{0,4}\b/,
  /\b(?:\d[\s-]?){12,18}\d\b/,
  /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/,
  /(?:(?:\+|00)\d{1,3}[\s.-]?)?(?:\d[\s.-]?){9,14}\d/,
  /\b\d{1,4}[A-Za-z]?\s+(?:[A-Z][A-Za-z'-]+\s+){1,3}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Odos|Leoforos)\b/i,
  /\b(?:AMKA|A\.M\.K\.A\.?|AFM|A\.F\.M\.?|ΑΦΜ|NI(?:NO)?)\s*[:#]?\s*[A-Z0-9]{8,12}\b/i,
  /\b(?:for|to|deliver(?:ed)?\s+to|collected\s+by)\s+(?:Mr|Mrs|Ms|Miss|Dr|Kyria|Kyrios)\.?\s+[A-Z][A-Za-z'-]+|\b[Tt]he\s+[A-Z][A-Za-z'-]+\s+(?:family\b|household\b|οικογένεια)/,
];

export function intakeErrorField(detail: string, submitted?: IntakeValues): string {
  const text = detail.toLowerCase();
  if (/never carries a person|phone|contact|iban|card|address|email/.test(text)) {
    return (['title', 'donor', 'note'] as const).find(name => personShapes.some(shape => shape.test(submitted?.[name] ?? ''))) ?? '';
  }
  if (/donor/.test(text)) return 'donor';
  if (/title/.test(text)) return 'title';
  if (/quantity/.test(text)) return 'quantity';
  if (/use.?by/.test(text)) return 'use_by';
  if (/collection.?date/.test(text)) return 'collection_date';
  if (/hours|cold/.test(text)) return 'hours_unrefrigerated';
  if (/note/.test(text)) return 'note';
  return '';
}

export function AddOffer({ data, busy, mutate, error = '' }: { data: Workspace; busy: boolean; mutate: Mutate; error?: string }) {
  const [category, setCategory] = useState('ambient');
  const [unknown, setUnknown] = useState(true);
  const [example, setExample] = useState<keyof typeof examples>();
  const [submitted, setSubmitted] = useState<IntakeValues>();
  const seed = example ? examples[example] : undefined;
  const date = new Date(); date.setDate(date.getDate() + 1);
  const tomorrow = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  date.setDate(date.getDate() + 2);
  const useBy = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const chilled = ['chilled', 'frozen'].includes(category);
  const invalid = error ? intakeErrorField(error, submitted) : '';
  const mark = (name: string) => invalid === name ? { 'aria-invalid': true, 'aria-describedby': 'intake-error' } as const : {};
  const alertRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (error) { alertRef.current?.focus(); alertRef.current?.scrollIntoView?.({ block: 'center' }); } }, [error]);
  return <><a href="#/offers" className="back-link">← All offers</a><div className="page-heading"><div><p className="eyebrow">A DONATION TO COORDINATE</p><h1>Add an offer</h1><p>{data.mode === 'sandbox' ? 'Describe an invented donation for this sandbox. Do not enter real personal information.' : 'Record what the donor told you. Use organisation names only.'}</p></div></div>{data.mode === 'sandbox' && <section className="panel padded"><h2>Try an editable flow</h2><p>These examples fill the form. Your submission uses the real API and Strands sandbox; the outcome depends on the fields you submit.</p><div className="form-actions">{(['success', 'refusal', 'correction'] as const).map(name => <button type="button" className="secondary" key={name} disabled={busy} aria-describedby={busy ? 'examples-reason' : undefined} onClick={() => { setExample(name); setCategory(examples[name].category); setUnknown(true); }}>Try {name}</button>)}</div>{busy && <p className="small-note" id="examples-reason">Examples are paused while the workspace saves, loads or needs a refresh.</p>}{example === 'correction' && <p className="notice">The invented phone-shaped example must be refused. Submit once, remove the contact detail, then submit the corrected note. A refused intake creates no offer.</p>}</section>}<section className="panel padded"><form key={example || 'empty'} className="intake-form" onSubmit={e => { e.preventDefault(); const fields = Object.fromEntries(new FormData(e.currentTarget)); setSubmitted({ title: String(fields.title), donor: String(fields.donor), note: String(fields.note) }); void mutate('', 'add', { form: { ...fields, allergens_unknown: unknown } }); }}>
    <label>What is being donated?<input {...mark('title')} name="title" required maxLength={120} defaultValue={seed?.title} placeholder="For example, surplus bread and vegetables"/></label>
    <label>Donor organisation<input {...mark('donor')} name="donor" required maxLength={120} defaultValue={seed ? 'Demonstration food cooperative' : ''} placeholder="Organisation or business, never a person's name"/></label>
    <div className="form-grid"><label>Quantity<input {...mark('quantity')} name="quantity" required type="number" min="0.01" max="100000" step="0.01" defaultValue={seed ? '120' : ''}/></label><label>Unit<select {...mark('unit')} name="unit" defaultValue="kg"><option value="kg">Kilograms (kg)</option><option value="units">Units</option></select></label><label>Food category<select {...mark('category')} name="category" value={category} onChange={e => setCategory(e.target.value)}>{['ambient', 'chilled', 'frozen', 'produce', 'non-food'].map(c => <option key={c}>{c}</option>)}</select></label><label>Collection date<input {...mark('collection_date')} type="date" name="collection_date" required defaultValue={seed ? tomorrow : ''}/></label><label>Use by date (if known)<input {...mark('use_by')} type="date" name="use_by" defaultValue={seed ? useBy : ''}/></label>{chilled && <label>Hours out of refrigeration<input {...mark('hours_unrefrigerated')} name="hours_unrefrigerated" type="number" min="0" max="168" step="0.1" required defaultValue={example === 'refusal' ? '8' : ''}/><span className="small-note">Required for chilled or frozen food. Unknown cold-chain evidence cannot pass.</span></label>}</div>
    <label className="check-label"><input type="checkbox" checked={unknown} onChange={e => setUnknown(e.target.checked)}/>Allergens have not been established</label>{!unknown && <label>Declared allergens<input {...mark('allergens')} name="allergens" maxLength={200} placeholder="For example, gluten, sesame"/><span className="small-note">Comma-separated. An empty answer is recorded as unknown.</span></label>}
    <label>Donor's food and collection note<textarea {...mark('note')} name="note" maxLength={600} rows={4} defaultValue={seed?.note} placeholder="Describe the food and collection constraints. No names, addresses or contact details."/></label>{error && <div role="alert" id="intake-error" tabIndex={-1} ref={alertRef} className="error"><h2>The offer was not accepted</h2><p>{error}</p><p>{invalid ? 'Check the marked field' : 'Check the form'} and submit again. The rejected intake was not saved.</p></div>}<div className="form-actions"><button disabled={busy || !data.can_write} aria-describedby={!data.can_write ? 'intake-write-reason' : busy ? 'intake-busy-reason' : undefined}>{busy ? 'Filing offer…' : data.mode === 'sandbox' ? 'Add to sandbox' : 'File offer'}</button><a href="#/offers">Cancel</a>{busy && data.can_write && <p className="small-note" id="intake-busy-reason">Filing is paused while the workspace saves, loads or needs a refresh.</p>}{!data.can_write && <p className="notice" id="intake-write-reason">{data.authorization_note} The sandbox supports the complete intake journey.</p>}</div>
  </form></section><details className="panel padded"><summary>Import a donor CSV instead</summary><CsvIntake data={data} busy={busy} mutate={mutate}/></details></>;
}
