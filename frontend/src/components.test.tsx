import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { Offers, Status, Summary } from './components';
import { OfferDetail, runStep } from './OfferDetail';
import { History, PickupCard, Pickups } from './Pickups';
import { AddOffer, intakeErrorField, type IntakeValues } from './AddOffer';
import { row, workspace } from './test/fixtures';

it('filters offers by search and status, and links the intake', async () => {
  const user = userEvent.setup(); render(<Offers data={workspace()}/>);
  expect(screen.getByRole('link',{name:'+ Add offer'})).toHaveAttribute('href','#/offers/new');
  await user.type(screen.getByRole('searchbox'),'missing'); expect(screen.getByText('No offers match')).toBeVisible();
  await user.clear(screen.getByRole('searchbox')); await user.selectOptions(screen.getByLabelText('Filter status'),'blocked');
  expect(screen.getByText('No offers match')).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Clear search and status'})); expect(screen.getByText('Bread and vegetables')).toBeVisible();
  await user.selectOptions(screen.getByLabelText('Filter status'),'awaiting_approval'); expect(screen.getByText('Bread and vegetables')).toBeVisible();
});
it('shows live counts without claiming rescued weight', () => {
  const data=workspace(); data.mode='live'; data.pickups=[{offer_id:'offer-4471',title:'Bread',org:'Kitchen',quantity:96,unit:'kg',role:'duty manager',state:'claimed',agreed_at:'',plan_digest:'digest',run_id:'run'}];
  render(<Offers data={data}/>); expect(screen.getByText('A record does not confirm collection')).toBeVisible();
  render(<Status value="custom"/>); expect(screen.getByText('custom')).toBeVisible();
});
it('copies the full draft reasons or provides a manual recovery', async () => {
  const user=userEvent.setup(); const write=vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator,'clipboard',{value:{writeText:write},configurable:true});
  render(<Summary row={row}/>); await user.click(screen.getByText('Copy summary'));
  expect(write).toHaveBeenCalledWith(row.summary); expect(screen.getByRole('status')).toHaveTextContent('Copied');
  write.mockRejectedValue(new Error('denied')); await user.click(screen.getByText('Copy summary'));
  expect(screen.getByRole('status')).toHaveTextContent('Select and copy');
});
it('requires exact-plan consent and retains it after failure', async () => {
  const user=userEvent.setup(); const mutate=vi.fn().mockResolvedValue(false);
  render(<OfferDetail row={row} data={workspace()} busy={false} mutate={mutate}/>);
  expect(screen.getByText('144 kg')).toBeVisible(); expect(screen.getByText('Same-day service required.')).toBeVisible();
  expect(screen.getByText('Sandbox approval records your decision inside this synthetic session and publishes nothing.')).toBeVisible(); expect(screen.getByText(/is network policy, not universal or certified fairness/)).toBeVisible(); expect(screen.getByText(/does not claim an optimal knapsack solution/).closest('details')).not.toHaveAttribute('open');
  const split=screen.getByRole('table'); expect(within(split).getByText('Amounts you are approving')).toBeInTheDocument(); expect(within(split).getAllByRole('cell').map(cell=>cell.textContent)).toEqual([row.result.draft_allocations![0].org,`${row.result.draft_allocations![0].quantity} ${row.offer.unit}`]); expect(split).not.toHaveTextContent(/Same-day/); expect(screen.getByText(/^Left without a recipient: 144 kg$/)).toBeVisible(); expect(within(split).queryByRole('heading')).toBeNull();
  const approve=screen.getByRole('button',{name:'Approve in sandbox'}); expect(approve).toBeDisabled(); expect(screen.getByText('Available once you tick the box above.')).toBeVisible(); expect(approve).toHaveAttribute('aria-describedby');
  await user.click(screen.getByLabelText(/I have reviewed/)); expect(approve).not.toHaveAttribute('aria-describedby'); await user.click(approve);
  expect(mutate).toHaveBeenCalledWith('offer-4471','approve',expect.objectContaining({digest:row.plan!.digest,consent:true,key:row.plan!.key}));
  expect(screen.getByRole('checkbox')).toBeChecked();
  mutate.mockResolvedValue(true); await user.click(approve); expect(screen.getByRole('checkbox')).not.toBeChecked();
  await user.click(screen.getByText('Recalculate the split')); expect(mutate).toHaveBeenLastCalledWith('offer-4471','run');
});
it('lists the exact amounts only for a consistent plan', () => {
  render(<OfferDetail row={{...row,plan:{...row.plan!,run_id:'another-run'}}} data={workspace()} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByText('Allocation quantities or run identity are unavailable or inconsistent. Refresh and review before approving.')).toBeVisible(); expect(screen.queryByRole('table')).toBeNull(); expect(screen.queryByText(/Left without a recipient/)).toBeNull();
});
it('renders missing, running, refused, ready and already-recorded states truthfully', () => {
  const data=workspace(); const mutate=vi.fn();
  const {rerender}=render(<OfferDetail data={data} busy={false} mutate={mutate}/>); expect(screen.getByText('Offer not found')).toBeVisible();
  const ready={...row,status:'not_started',result:{},plan:null,offer:{...row.offer,use_by:'',allergens:null}};
  rerender(<OfferDetail row={ready} data={data} busy={false} mutate={mutate}/>); expect(screen.getByText('Unknown; needs checking')).toBeVisible(); expect(screen.getByText('Not provided')).toBeVisible();
  rerender(<OfferDetail row={{...ready,status:'running',progress:undefined}} data={data} busy={false} mutate={mutate}/>); expect(screen.getByRole('status')).toHaveTextContent('Starting the runner'); expect(screen.getByText('Specialists check food safety, capacity, equity and premises where each applies to this category')).toBeVisible(); expect(screen.getByText('A split is proposed for your approval, or the run stops with the reason')).toBeVisible();
  rerender(<OfferDetail row={{...ready,status:'running',progress:row.progress}} data={data} busy mutate={mutate}/>); expect(screen.getByText('Working…')).toBeDisabled();
  rerender(<OfferDetail row={{...ready,result:{outcome:'blocked'},offer:{...row.offer,allergens:[]}}} data={data} busy={false} mutate={mutate}/>); expect(screen.getByText('Declared none')).toBeVisible(); expect(screen.getByText(/No allocation was approved/)).toBeVisible();
  rerender(<OfferDetail row={{...row,plan:{...row.plan!,recorded:true}}} data={data} busy={false} mutate={mutate}/>); expect(screen.getByText('The recorded plan')).toBeVisible(); expect(screen.getByText('Open collection tasks →')).toBeVisible();
});
it('marks the run steps done, in progress and not started from the reported stage', () => {
  const data=workspace(); const mutate=vi.fn(); const running={...row,status:'running',result:{},plan:null};
  const steps=()=>within(screen.getByText('Reading the offer').closest('ol')!).getAllByRole('listitem');
  const states=()=>steps().map(item=>item.querySelector('.run-step-state')!.textContent);
  const currentIndex=()=>steps().findIndex(item=>item.getAttribute('aria-current')==='step');
  const {rerender}=render(<OfferDetail row={{...running,progress:undefined}} data={data} busy={false} mutate={mutate}/>);
  expect(steps()).toHaveLength(4); expect(states()).toEqual(['In progress','Not started','Not started','Not started']); expect(currentIndex()).toBe(0);
  rerender(<OfferDetail row={{...running,progress:{stage:'the specialists are reading the filing',specialists_answered:2}}} data={data} busy={false} mutate={mutate}/>);
  expect(states()).toEqual(['Done','In progress','Not started','Not started']); expect(currentIndex()).toBe(1); expect(steps().filter(item=>item.hasAttribute('aria-current'))).toHaveLength(1);
  rerender(<OfferDetail row={{...running,progress:{stage:'done',specialists_answered:4}}} data={data} busy={false} mutate={mutate}/>);
  expect(states()).toEqual(['Done','Done','Done','In progress']); expect(currentIndex()).toBe(3);
  rerender(<OfferDetail row={{...running,progress:{stage:'Checking the draft',specialists_answered:4}}} data={data} busy={false} mutate={mutate}/>);
  expect(states()).toEqual(['In progress','Not started','Not started','Not started']); expect(currentIndex()).toBe(0);
  expect(runStep('the gate is checking the draft')).toBe(2); expect(runStep(' Deciding who wakes ')).toBe(1); expect(runStep('constructor')).toBe(0); expect(runStep('')).toBe(0);
});
it('points a disabled approval at the reason its consent box is disabled instead of asking to tick it', () => {
  const data=workspace(); const tick='Available once you tick the box above.';
  const {rerender}=render(<OfferDetail row={row} data={data} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByRole('checkbox')).toBeEnabled(); expect(screen.getByText('Approve in sandbox')).toHaveAttribute('aria-describedby',screen.getByText(tick).id);
  rerender(<OfferDetail row={row} data={data} busy mutate={vi.fn()}/>);
  expect(screen.getByRole('checkbox')).toBeDisabled(); expect(screen.queryByText(tick)).toBeNull();
  expect(screen.getByText('Recording decision…')).toHaveAttribute('aria-describedby',screen.getByText('Approval paused while the workspace loads, saves or needs a refresh.').id);
  rerender(<OfferDetail row={{...row,plan:{...row.plan!,run_id:'another-run'}}} data={data} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByRole('checkbox')).toBeDisabled(); expect(screen.queryByText(tick)).toBeNull();
  expect(screen.getByText('Approve in sandbox')).toHaveAttribute('aria-describedby',screen.getByText('Allocation quantities or run identity are unavailable or inconsistent. Refresh and review before approving.').id);
  rerender(<OfferDetail row={row} data={{...data,mode:'live',can_write:false}} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByRole('checkbox')).toBeDisabled(); expect(screen.queryByText(tick)).toBeNull();
  expect(screen.getByText('Approve and publish')).toBeDisabled(); expect(screen.getByText('Approve and publish')).toHaveAttribute('aria-describedby',screen.getByText(data.authorization_note).id);
});
it('clearly gates live approval and displays its consequence', async () => {
  const data=workspace(); data.mode='live'; data.can_write=false;
  const {rerender}=render(<OfferDetail row={row} data={data} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByText('Approve and publish')).toBeDisabled(); expect(screen.getByText(/permanent public allocation/)).toBeVisible();
  rerender(<OfferDetail row={row} data={{...data,can_write:true}} busy mutate={vi.fn()}/>); expect(screen.getByText('Recording decision…')).toBeDisabled(); expect(screen.getByText('Approval paused while the workspace loads, saves or needs a refresh.')).toBeVisible();
});
it('takes a pickup from claim through scheduling and explicit confirmation', async () => {
  const data=workspace(); const mutate=vi.fn().mockResolvedValue(true); const user=userEvent.setup();
  data.pickups=[{offer_id:'offer-4471',title:'Bread',org:'Kitchen',quantity:96,unit:'kg',role:'',state:'unclaimed',agreed_at:'',plan_digest:'digest',run_id:'run'}];
  const {rerender}=render(<Pickups data={data} busy={false} mutate={mutate}/>);
  await user.selectOptions(screen.getByLabelText('Collecting role'),'kitchen lead'); await user.click(screen.getByText('Claim this share'));
  expect(mutate).toHaveBeenLastCalledWith('offer-4471','pickup',expect.objectContaining({action:'claim',role:'kitchen lead',digest:'digest'}));
  data.pickups[0]={...data.pickups[0],state:'claimed',role:'kitchen lead'};
  rerender(<Pickups data={data} busy={false} mutate={mutate}/>);
  expect(screen.getByText('Save collection time')).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Collection time (your local time)'),{target:{value:'2026-10-01T12:00'}});
  await user.click(screen.getByText('Save collection time')); expect(mutate).toHaveBeenLastCalledWith('offer-4471','pickup',expect.objectContaining({action:'schedule'}));
  expect(screen.getByText('Confirm collection')).toBeDisabled(); await user.click(screen.getByLabelText(/This collection actually/)); await user.click(screen.getByText('Confirm collection'));
  expect(mutate).toHaveBeenLastCalledWith('offer-4471','pickup',expect.objectContaining({action:'confirm',consent:true}));
  data.pickups[0]={...data.pickups[0],state:'confirmed',agreed_at:'2026-10-01T12:00:00Z'};
  rerender(<Pickups data={data} busy={false} mutate={mutate}/>); expect(screen.getByText('No collection tasks here')).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Show all collections'})); expect(screen.getByLabelText('Show')).toHaveValue('all');
  await user.selectOptions(screen.getByLabelText('Show'),'confirmed'); expect(screen.getByText('Confirmed collected')).toBeVisible();
  expect(screen.getByText('Simulation confirmed')).toBeVisible();
  expect(screen.queryByText('Claim this share')).not.toBeInTheDocument();
  data.mode='live'; rerender(<Pickups data={data} busy={false} mutate={mutate}/>); expect(screen.getByText(/coordinator register/)).toBeVisible();
  data.pickups[0].state='invalidated'; await user.selectOptions(screen.getByLabelText('Show'),'all'); rerender(<Pickups data={data} busy={false} mutate={mutate}/>); expect(screen.getByText(/allocation changed or the commitment expired/)).toBeVisible();
  await user.selectOptions(screen.getByLabelText('Show'),'invalidated'); expect(within(screen.getByRole('article')).getByText('Invalidated')).toBeVisible();
});
it('shows empty pickups and live authorization instead of unusable controls', () => {
  const data=workspace(); const {rerender}=render(<Pickups data={data} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByText(/Review an offer and approve/)).toBeVisible();
  data.can_write=false; data.pickups=[{offer_id:'offer-4471',title:'Bread',org:'Kitchen',quantity:96,unit:'kg',role:'duty manager',state:'overdue',agreed_at:'2020-01-01T12:00Z',plan_digest:'d',run_id:'r'}];
  rerender(<Pickups data={data} busy={false} mutate={vi.fn()}/>); expect(screen.getByText(data.authorization_note)).toBeVisible();
});
it('explains paused and unticked pickup actions beside their disabled buttons', () => {
  const data=workspace(); const mutate=vi.fn();
  data.pickups=[{offer_id:'offer-4471',title:'Bread',org:'Kitchen',quantity:96,unit:'kg',role:'',state:'unclaimed',agreed_at:'',plan_digest:'digest',run_id:'run'}];
  const {rerender}=render(<Pickups data={data} busy mutate={mutate}/>);
  const paused=()=>screen.getByText('Actions on this share are paused while the workspace loads, saves or needs a refresh.');
  expect(paused()).toBeVisible(); expect(screen.getByText('Claim this share')).toHaveAttribute('aria-describedby',paused().id);
  expect(paused().nextElementSibling).toBe(screen.getByText('Claim this share').closest('form')); expect(screen.getByRole('heading',{name:'Kitchen'}).nextElementSibling).not.toBe(paused());
  data.pickups[0]={...data.pickups[0],state:'claimed',role:'kitchen lead'};
  rerender(<Pickups data={data} busy mutate={mutate}/>);
  const observe=screen.getByText('Available once you tick the observation box above.');
  expect(paused()).toBeVisible(); expect(observe).toBeVisible();
  expect(paused().nextElementSibling).toBe(screen.getByText('Save collection time').closest('form'));
  expect(screen.getByText('Save handoff report')).toHaveAttribute('aria-describedby',`${paused().id} ${observe.id}`);
  expect(screen.getByText('Save collection time')).toHaveAttribute('aria-describedby',`${paused().id} ${screen.getByText('Choose a future time within the next 14 days.').id}`);
  expect(screen.getByText('Confirm collection')).toHaveAttribute('aria-describedby',`${paused().id} ${screen.getByText('Confirm arrival before marking this share collected.').id}`);
  rerender(<PickupCard item={{...data.pickups[0],state:'confirmed'}} data={data} busy mutate={mutate} today="2026-09-09"/>);
  expect(screen.getByText('Simulation confirmed')).toBeVisible(); expect(screen.queryByText(/paused while the workspace loads/)).not.toBeInTheDocument();
});

it('requires renewed observation consent and retains it after a failed handoff save', async () => {
  const data = workspace(); const user = userEvent.setup();
  data.pickups = [{offer_id:'offer-4471',title:'Bread',org:'Kitchen',quantity:96,
    unit:'kg',role:'duty manager',state:'claimed',agreed_at:'',plan_digest:'digest',run_id:'run'}];
  const mutate = vi.fn().mockResolvedValue(false);
  render(<Pickups data={data} busy={false} mutate={mutate}/>);
  const save = screen.getByText('Save handoff report');
  const consent = screen.getByLabelText(/I observed this handoff event/);
  expect(save).toBeDisabled();
  await user.click(consent);
  await user.selectOptions(screen.getByLabelText('Handoff observation'), 'recipient_ready');
  expect(consent).not.toBeChecked();
  await user.click(consent);
  await user.selectOptions(screen.getByLabelText('Reporting role'), 'kitchen lead');
  expect(consent).not.toBeChecked();
  await user.click(consent); await user.click(save);
  expect(mutate).toHaveBeenLastCalledWith('offer-4471', 'pickup', {
    digest:'digest',run_id:'run',org:'Kitchen',action:'feedback',
    feedback:'recipient_ready',role:'kitchen lead',consent:true,
  });
  expect(consent).toBeChecked();
  mutate.mockResolvedValue(true); await user.click(save);
  expect(consent).not.toBeChecked();
  expect(screen.getByText('Confirm collection')).toBeDisabled();
  expect(screen.getByLabelText('Show')).toBeVisible();
});
it('labels handoff reports in coordinator words and keeps unknown report codes readable', () => {
  const data = workspace();
  data.pickups = [{offer_id:'offer-4471',title:'Bread',org:'Kitchen',quantity:96,unit:'kg',role:'duty manager',state:'claimed',agreed_at:'',plan_digest:'digest',run_id:'run',
    feedback:[{code:'driver_ready',role:'duty manager',at:1757840400},{code:'custom_code',role:'kitchen lead',at:1757844000}]}];
  render(<Pickups data={data} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByText(/^Collector ready ·/)).toBeVisible();
  expect(screen.getByText(/^custom code ·/)).toBeVisible();
});
it('shows current and superseded history without rewriting old records', () => {
  const data=workspace(); const {rerender}=render(<History data={data}/>); expect(screen.getByText('No records yet')).toBeVisible();
  data.records=[{key:'records/offer-4471.md',offer_id:'offer-4471',run_id:'r',content_digest:'d',published_at:1,superseded_by:'records/offer-4471-c2.md',mode:'sandbox'}];
  rerender(<History data={data}/>); expect(screen.getByText(/^Superseded by/)).toBeVisible(); expect(screen.getByText('Simulation')).toBeVisible();
  data.mode='live'; data.records[0].mode='live'; data.records[0].superseded_by=''; rerender(<History data={data}/>); expect(screen.getByText('Current record in this history')).toBeVisible(); expect(screen.getByText('Published',{exact:true})).toBeVisible();
});
it('submits an accessible intake form, retains fields, and asks cold-chain evidence', async () => {
  const user=userEvent.setup(); const mutate=vi.fn().mockResolvedValue(false); const data=workspace();
  const {rerender}=render(<AddOffer data={data} busy={false} mutate={mutate}/>);
  await user.type(screen.getByLabelText('What is being donated?'),'Test bread'); await user.type(screen.getByLabelText('Donor organisation'),'Demo bakery');
  await user.type(screen.getByLabelText('Quantity'),'120'); fireEvent.change(screen.getByLabelText('Collection date'),{target:{value:'2026-09-12'}});
  await user.selectOptions(screen.getByLabelText('Food category'),'chilled'); fireEvent.change(screen.getByLabelText(/Hours out of refrigeration/),{target:{value:'0'}});
  await user.click(screen.getByLabelText('Allergens have not been established')); await user.type(screen.getByLabelText(/Declared allergens/),'gluten');
  await user.click(screen.getByText('Add to sandbox')); expect(mutate).toHaveBeenCalledWith('','add',expect.objectContaining({form:expect.objectContaining({title:'Test bread',category:'chilled',allergens:'gluten',allergens_unknown:false})}));
  expect(screen.getByLabelText('What is being donated?')).toHaveValue('Test bread');
  rerender(<AddOffer data={{...data,mode:'live',can_write:false}} busy={false} mutate={mutate}/>); expect(screen.getByText('File offer')).toBeDisabled();
  rerender(<AddOffer data={data} busy mutate={mutate}/>); expect(screen.getByText('Filing offer…')).toBeDisabled();
});
const personRefusal = (what: string) => `That contains ${what}. A published record never carries a person, so this would be refused later anyway. Describe the food, not the people.`;
const cleanIntake: IntakeValues = { title: 'Courtyard vegetables', donor: 'Demonstration cooperative', note: 'Collect before evening.' };
const intakeFieldCases: [string, IntakeValues | undefined, string][] = [
  ['Remove the phone number', undefined, ''], ['Remove the phone number', { ...cleanIntake, note: 'Call 6941234567' }, 'note'],
  [personRefusal('what reads as a phone number'), { ...cleanIntake, donor: 'Fournos 6941234567' }, 'donor'],
  [personRefusal('what reads as a phone number'), { ...cleanIntake, title: 'Bread 6941234567', note: 'Call 6941234567' }, 'title'],
  [personRefusal('what reads as a phone number'), cleanIntake, ''], [personRefusal('an email address'), { ...cleanIntake, donor: 'orders@fournos.gr' }, 'donor'],
  [personRefusal('a street address'), { ...cleanIntake, note: 'Collect at 14 Fokionos Negri Street' }, 'note'],
  [personRefusal('a named household'), { ...cleanIntake, title: 'Bread for the Papadopoulos family' }, 'title'],
  ['Quantity must be positive', undefined, 'quantity'], ['use_by precedes collection', undefined, 'use_by'],
  ['collection_date is required', undefined, 'collection_date'], ['hours_unrefrigerated required', undefined, 'hours_unrefrigerated'],
  ['Donor name looks personal', undefined, 'donor'], ['Title is too long', undefined, 'title'], ['The note is too long', undefined, 'note'], ['Unknown problem', undefined, ''],
];
it.each(intakeFieldCases)('maps the refused intake detail %s with submitted values %o to the field %s', (detail, submitted, field) => {
  expect(intakeErrorField(detail, submitted)).toBe(field);
});
it('shows a refused intake inside the form, marks the refused field and explains paused controls', () => {
  const data=workspace(); const mutate=vi.fn(); const note=()=>screen.getByLabelText("Donor's food and collection note");
  const {rerender}=render(<AddOffer data={data} busy={false} mutate={mutate}/>);
  fireEvent.change(note(),{target:{value:'Call 6941234567'}}); fireEvent.submit(note().closest('form')!);
  rerender(<AddOffer data={data} busy={false} mutate={mutate} error="Remove the phone number"/>);
  expect(screen.getByRole('alert')).toHaveTextContent('Check the marked field'); expect(screen.getByRole('alert')).toHaveTextContent('The rejected intake was not saved.');
  expect(note()).toHaveAttribute('aria-invalid','true'); expect(note()).toHaveAttribute('aria-describedby','intake-error'); expect(screen.getByLabelText('Donor organisation')).not.toHaveAttribute('aria-invalid');
  rerender(<AddOffer data={data} busy={false} mutate={mutate} error="Unknown problem"/>);
  expect(screen.getByRole('alert')).toHaveTextContent('Check the form'); expect(note()).not.toHaveAttribute('aria-invalid');
  rerender(<AddOffer data={data} busy mutate={mutate}/>); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByText('Examples are paused while the workspace saves, loads or needs a refresh.')).toBeVisible(); expect(screen.getByText('Try success')).toHaveAttribute('aria-describedby','examples-reason');
  expect(screen.getByText('Filing is paused while the workspace saves, loads or needs a refresh.')).toBeVisible(); expect(screen.getByText('Filing offer…')).toHaveAttribute('aria-describedby','intake-busy-reason');
});
