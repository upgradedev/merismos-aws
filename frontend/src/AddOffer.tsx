import { useState } from 'react';
import type { Mutate } from './OfferDetail';
import type { Workspace } from './types';

export function AddOffer({ data, busy, mutate }: { data: Workspace; busy: boolean; mutate: Mutate }) {
  const [category, setCategory] = useState('ambient');
  const [unknown, setUnknown] = useState(true);
  const chilled = ['chilled', 'frozen'].includes(category);
  return <><a href="#/offers" className="back-link">← All offers</a><div className="page-heading"><div><p className="eyebrow">A DONATION TO COORDINATE</p><h1>Add an offer</h1><p>{data.mode === 'sandbox' ? 'Describe an invented donation for this sandbox. Do not enter real personal information.' : 'Record what the donor told you. Use organisation names only.'}</p></div></div><section className="panel padded"><form className="intake-form" onSubmit={e => { e.preventDefault(); const fields = Object.fromEntries(new FormData(e.currentTarget)); void mutate('', 'add', { form: { ...fields, allergens_unknown: unknown } }); }}>
    <label>What is being donated?<input name="title" required maxLength={120} placeholder="For example, surplus bread and vegetables"/></label>
    <label>Donor organisation<input name="donor" required maxLength={120} placeholder="Organisation or business, never a person's name"/></label>
    <div className="form-grid"><label>Quantity<input name="quantity" required type="number" min="0.01" max="100000" step="0.01"/></label><label>Unit<select name="unit" defaultValue="kg"><option value="kg">Kilograms (kg)</option><option value="units">Units</option></select></label><label>Food category<select name="category" value={category} onChange={e => setCategory(e.target.value)}>{['ambient', 'chilled', 'frozen', 'produce', 'non-food'].map(c => <option key={c}>{c}</option>)}</select></label><label>Collection date<input type="date" name="collection_date" required/></label><label>Use by date (if known)<input type="date" name="use_by"/></label>{chilled && <label>Hours out of refrigeration<input name="hours_unrefrigerated" type="number" min="0" max="168" step="0.1" required/><span className="small-note">Required for chilled or frozen food. Unknown cold-chain evidence cannot pass.</span></label>}</div>
    <label className="check-label"><input type="checkbox" checked={unknown} onChange={e => setUnknown(e.target.checked)}/>Allergens have not been established</label>{!unknown && <label>Declared allergens<input name="allergens" maxLength={200} placeholder="For example, gluten, sesame"/><span className="small-note">Comma-separated. An empty answer is recorded as unknown.</span></label>}
    <label>Donor's food and collection note<textarea name="note" maxLength={600} rows={4} placeholder="Describe the food and collection constraints. No names, addresses or contact details."/></label><div className="form-actions"><button disabled={busy || !data.can_write}>{busy ? 'Filing offer…' : data.mode === 'sandbox' ? 'Add to sandbox' : 'File offer'}</button><a href="#/offers">Cancel</a></div>{!data.can_write && <p className="notice">{data.authorization_note} The sandbox supports the complete intake journey.</p>}
  </form></section></>;
}
