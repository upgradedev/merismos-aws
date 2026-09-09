import type { OfferRow, Workspace } from '../types';
export const row: OfferRow = {
  offer: {id:'offer-4471', title:'Bread and vegetables', donor:'Synthetic bakery', category:'ambient', quantity:240, unit:'kg', collection_date:'2026-09-10', use_by:'2026-09-11', allergens:['gluten'], note:'Collect before evening.'},
  status:'awaiting_approval', progress:{stage:'Checking the draft', specialists_answered:4},
  result: {run_id:'run-example', outcome:'awaiting_approval', note:'The gate passed. Approval is required.', draft_body:'Exact record bytes', draft_allocations:[{org:'Omonoia Soup Kitchen', quantity:96, reason:'Same-day service, 40% ceiling.', share_of_offer:0.4}], draft_barred_because:{'Kypseli Pantry':'Same-day service required.'}, envelopes:[{specialist:'food-safety',status:'ok',reason:'Shelf life checked.',findings:[{severity:'medium',detail:'Same-day delivery.'}]}]},
  plan: {key:'records/offer-4471.md',digest:'a'.repeat(64),body:'Exact record bytes',run_id:'run-example',recorded:false,evidence_digest:'evidence'},
  summary:'SYNTHETIC DEMO · SANDBOX\nDRAFT. Omonoia Soup Kitchen: 96 kg. Kypseli Pantry: same-day service required.',
};
export function workspace(): Workspace { return structuredClone({mode:'sandbox',version:1,network:'kypseli-network',synthetic:true,offers:[row],pickups:[],records:[],roles:['duty manager','kitchen lead'],can_write:true,provider:'scripted-planner/1.0.0',authorization_note:'Live changes require an authenticated network coordinator.',expires_at:9999999999}); }
