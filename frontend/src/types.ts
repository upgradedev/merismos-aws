export type Mode = 'sandbox' | 'live';
export interface Offer { id: string; title: string; donor: string; category: string; quantity: number; unit: string; collection_date: string; use_by: string; allergens: string[] | null; note: string; hours_unrefrigerated?: number | null }
export interface Allocation { org: string; quantity: number; reason: string; share_of_offer: number; evidence_sources?: string[] }
export interface FairnessCap { share: number; source: string }
export interface Result { run_id?: string; outcome?: string; note?: string; draft_body?: string; draft_allocations?: Allocation[]; draft_barred_because?: Record<string, string>; fairness_cap?: FairnessCap | null; envelopes?: {specialist: string; status: string; reason: string; findings: {detail: string; severity: string}[]}[] }
export interface Plan { key: string; digest: string; body: string; run_id: string; recorded: boolean; evidence_digest: string }
export interface Replan { org: string; capacity: number; unit: string; previous_quantity: number; before: Result; before_digest: string; before_recorded: boolean; before_key: string; source: string }
export interface OfferRow { offer: Offer; status: string; result: Result; plan: Plan | null; summary: string; progress?: { stage: string; specialists_answered: number }; replan?: Replan | null }
export interface Pickup { offer_id: string; title: string; org: string; quantity: number; unit: string; role: string; state: string; agreed_at: string; plan_digest: string; commitment_digest?: string; run_id: string; claimed_at?: number; confirmed_at?: number | null; feedback?: {code: string; role: string; at: number}[] }
export interface RecordRow { key: string; offer_id: string; run_id: string; content_digest: string; published_at: number; superseded_by: string; mode: Mode }
export interface Workspace { mode: Mode; version: number; network: string; synthetic: true; offers: OfferRow[]; pickups: Pickup[]; records: RecordRow[]; roles: string[]; can_write: boolean; provider: string; authorization_note: string; expires_at: number; operations?: {id: string; offer_id: string; action: string; status: string}[] }
