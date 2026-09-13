import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { Offers, Status, Summary } from './components';
import { OfferDetail } from './OfferDetail';
import { History, PickupCard, Pickups } from './Pickups';
import { AddOffer } from './AddOffer';
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
  const approve=screen.getByRole('button',{name:'Approve in sandbox'}); expect(approve).toBeDisabled(); expect(screen.getByText('Available once you tick the box above.')).toBeVisible(); expect(approve).toHaveAttribute('aria-describedby');
  await user.click(screen.getByLabelText(/I have reviewed/)); expect(approve).not.toHaveAttribute('aria-describedby'); await user.click(approve);
  expect(mutate).toHaveBeenCalledWith('offer-4471','approve',expect.objectContaining({digest:row.plan!.digest,consent:true,key:row.plan!.key}));
  expect(screen.getByRole('checkbox')).toBeChecked();
  mutate.mockResolvedValue(true); await user.click(approve); expect(screen.getByRole('checkbox')).not.toBeChecked();
  await user.click(screen.getByText('Recalculate the split')); expect(mutate).toHaveBeenLastCalledWith('offer-4471','run');
});
it('renders missing, running, refused, ready and already-recorded states truthfully', () => {
  const data=workspace(); const mutate=vi.fn();
  const {rerender}=render(<OfferDetail data={data} busy={false} mutate={mutate}/>); expect(screen.getByText('Offer not found')).toBeVisible();
  const ready={...row,status:'not_started',result:{},plan:null,offer:{...row.offer,use_by:'',allergens:null}};
  rerender(<OfferDetail row={ready} data={data} busy={false} mutate={mutate}/>); expect(screen.getByText('Unknown; needs checking')).toBeVisible(); expect(screen.getByText('Not provided')).toBeVisible();
  rerender(<OfferDetail row={{...ready,status:'running',progress:undefined}} data={data} busy={false} mutate={mutate}/>); expect(screen.getByRole('status')).toHaveTextContent('Starting the runner'); expect(screen.getByText('Four specialists check food safety, capacity, equity and premises')).toBeVisible();
  rerender(<OfferDetail row={{...ready,status:'running',progress:row.progress}} data={data} busy mutate={mutate}/>); expect(screen.getByText('Working…')).toBeDisabled();
  rerender(<OfferDetail row={{...ready,result:{outcome:'blocked'},offer:{...row.offer,allergens:[]}}} data={data} busy={false} mutate={mutate}/>); expect(screen.getByText('Declared none')).toBeVisible(); expect(screen.getByText(/No allocation was approved/)).toBeVisible();
  rerender(<OfferDetail row={{...row,plan:{...row.plan!,recorded:true}}} data={data} busy={false} mutate={mutate}/>); expect(screen.getByText('The recorded plan')).toBeVisible(); expect(screen.getByText('Open collection tasks →')).toBeVisible();
});
it('clearly gates live approval and displays its consequence', async () => {
  const data=workspace(); data.mode='live'; data.can_write=false;
  const {rerender}=render(<OfferDetail row={row} data={data} busy={false} mutate={vi.fn()}/>);
  expect(screen.getByText('Approve and publish')).toBeDisabled(); expect(screen.getByText(/permanent public allocation/)).toBeVisible();
  rerender(<OfferDetail row={row} data={{...data,can_write:true}} busy mutate={vi.fn()}/>); expect(screen.getByText('Recording decision…')).toBeDisabled(); expect(screen.getByText('Approval paused until the current change is saved.')).toBeVisible();
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
  const paused=()=>screen.getByText('Actions on this share are paused until the current change is saved.');
  expect(paused()).toBeVisible(); expect(screen.getByText('Claim this share')).toHaveAttribute('aria-describedby',paused().id);
  data.pickups[0]={...data.pickups[0],state:'claimed',role:'kitchen lead'};
  rerender(<Pickups data={data} busy mutate={mutate}/>);
  const observe=screen.getByText('Available once you tick the observation box above.');
  expect(paused()).toBeVisible(); expect(observe).toBeVisible();
  expect(screen.getByText('Save handoff report')).toHaveAttribute('aria-describedby',`${paused().id} ${observe.id}`);
  expect(screen.getByText('Save collection time')).toHaveAttribute('aria-describedby',`${paused().id} ${screen.getByText('Choose a future time within the next 14 days.').id}`);
  expect(screen.getByText('Confirm collection')).toHaveAttribute('aria-describedby',`${paused().id} ${screen.getByText('Confirm arrival before marking this share collected.').id}`);
  rerender(<PickupCard item={{...data.pickups[0],state:'confirmed'}} data={data} busy mutate={mutate} today="2026-09-09"/>);
  expect(screen.getByText('Simulation confirmed')).toBeVisible(); expect(screen.queryByText(/paused until the current change/)).not.toBeInTheDocument();
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
