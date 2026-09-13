import { useState } from 'react';
import { routeLink } from './routes';
import type { Workspace } from './types';

interface UserJourneysViewProps {
  data?: Workspace;
}

interface JourneyStep {
  id: string;
  number: string;
  title: string;
  summary: string;
  actor: string;
  timeToComplete: string;
  constraints: string[];
  awsServices: string[];
  artifactProduced: string;
  deepDive: string;
}

const JOURNEYS: JourneyStep[] = [
  {
    id: 'intake',
    number: '01',
    title: 'Surplus Donation Ingest & Safety Classification',
    summary: 'Donors register available inventory. Merismos validates hygiene guidelines, expiry dates, and thermal constraints.',
    actor: 'Food Donor (Supermarket Manager / Baker)',
    timeToComplete: '< 60 seconds',
    constraints: [
      'Expiry date must be >= today',
      'Storage category (ambient, refrigerated, frozen) verified',
      'Quantity and packaging units strictly enforced',
      'Collection window must be clearly bounded',
    ],
    awsServices: ['API Gateway', 'AWS Lambda (Intake Service)', 'Amazon DynamoDB'],
    artifactProduced: 'Structured Offer Entity (`offer-4471`) with safety tags',
    deepDive: 'When a donor submits an offer, the intake validator checks that perishable chilled goods (like yoghurt or fresh meat) are flagged with immediate refrigeration requirements. If an offer has already expired or lacks safe packaging, it is rejected at the gate with actionable feedback.',
  },
  {
    id: 'arbitration',
    number: '02',
    title: 'Multi-Agent Equity & Capacity Arbitration',
    summary: 'AWS Strands agents independently evaluate community shelter needs, distance, and historical fair-share quotas.',
    actor: 'AWS Strands Multi-Agent Fleet',
    timeToComplete: '< 3 seconds',
    constraints: [
      'Shelter refrigeration capacity cannot be exceeded',
      'Same-day delivery constraints strictly honored',
      'Fair-share equity index: organisations skipped recently receive priority',
      'Zero unaccounted surplus: all kilos allocated or declared unallocated',
    ],
    awsServices: ['AWS Strands Agents SDK', 'Amazon Bedrock (Semantic Constraints)', 'AWS Lambda'],
    artifactProduced: 'Candidate Allocation Plan with mathematical justifications per recipient',
    deepDive: 'Rather than a black-box greedy algorithm, Merismos uses a fleet of agentic evaluators representing the five distinct community organisations. Each agent evaluates its shelter’s current pantry level and volunteer capacity, negotiating an equitable division that maximizes community benefit.',
  },
  {
    id: 'approval',
    number: '03',
    title: 'Coordinator Review & Return-of-Control',
    summary: 'The human coordinator verifies the rationale, reviews recipient breakdowns, and signs off before any action is taken.',
    actor: 'Volunteer Coordinator (Human in the Loop)',
    timeToComplete: '< 30 seconds',
    constraints: [
      'Human must explicitly review recipient reasons',
      'Single-click approval with cryptographic consent hash',
      'Option to re-run with modified constraints or reject allocation',
      'Zero automated dispatches without human authorization',
    ],
    awsServices: ['CloudFront (Authenticated Operations Cockpit)', 'AWS Lambda (Approval Guard)'],
    artifactProduced: 'Approved Dispatch Execution Record with HMAC Signature',
    deepDive: 'No food is promised and no driver is dispatched without explicit human consent. The coordinator sees why each shelter was selected and why others were excluded (e.g. "Kypseli Shelter excluded: no refrigerated transport available for chilled poultry").',
  },
  {
    id: 'proof',
    number: '04',
    title: 'Public S3 Proof Ledger & Community Custody',
    summary: 'The finalized allocation is sealed and published to a public Amazon S3 bucket for immutable community transparency.',
    actor: 'Community & Donor Network',
    timeToComplete: 'Immediate (< 1s)',
    constraints: [
      'Record is content-addressed and tamper-evident',
      'Available publicly via HTTPS without login',
      'Pickup confirmation is recorded as a separate immutable event',
      'Full audit trail preserved across session restarts',
    ],
    awsServices: ['Amazon S3 (Public Proof Bucket)', 'Amazon EventBridge', 'Amazon SES'],
    artifactProduced: 'Public Markdown Proof Record (e.g. `offer-4471.md` on S3)',
    deepDive: 'Transparency eliminates neighborhood suspicion and political favoritism. Every resident, donor, and NGO director can audit the exact distribution schedule, verifying that donated food went to feed vulnerable people rather than disappearing into private hands.',
  },
];

export function UserJourneysView({ data }: UserJourneysViewProps) {
  const [selectedId, setSelectedId] = useState('intake');
  const activeJourney = JOURNEYS.find(j => j.id === selectedId) || JOURNEYS[0];

  return (
    <div className="journeys-view" style={{ maxWidth: '1280px', margin: '0 auto', padding: '16px 0 48px' }}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">STEP-BY-STEP USER LIFECYCLE</p>
          <h1>Civic Food Rescue Journeys</h1>
          <p>How Merismos coordinates donors, multi-agent arbitration, human approval, and public verification.</p>
        </div>
        <a className="button" href={routeLink('/workspace')}>
          Open Active Workspace →
        </a>
      </div>

      {/* Navigation Tabs for Journeys */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px', marginBottom: '28px' }}>
        {JOURNEYS.map(j => {
          const isSelected = j.id === selectedId;
          return (
            <button
              key={j.id}
              onClick={() => setSelectedId(j.id)}
              className="panel"
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'stretch',
                textAlign: 'left',
                padding: '16px',
                cursor: 'pointer',
                borderColor: isSelected ? 'var(--teal)' : 'var(--border)',
                background: isSelected ? 'var(--raised)' : 'var(--panel)',
                color: 'var(--text)',
                margin: 0,
                transition: 'border-color 0.15s, background-color 0.15s',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                <span style={{ fontSize: '0.875rem', fontWeight: 800, color: isSelected ? 'var(--teal)' : 'var(--secondary)' }}>
                  STAGE {j.number}
                </span>
                <span className="badge" style={{ fontSize: '0.75rem', padding: '2px 6px' }}>
                  {j.timeToComplete}
                </span>
              </div>
              <strong style={{ display: 'block', fontSize: '1rem', lineHeight: 1.3 }}>{j.title}</strong>
            </button>
          );
        })}
      </div>

      {/* Active Journey Detail Card */}
      <section className="panel padded" aria-labelledby="active-journey-title">
        <div className="section-heading" style={{ borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '20px' }}>
          <div>
            <span className="eyebrow">STAGE {activeJourney.number} DEEP DIVE</span>
            <h2 id="active-journey-title" style={{ fontSize: '1.6rem', marginTop: '4px' }}>{activeJourney.title}</h2>
            <p style={{ color: 'var(--secondary)', margin: '4px 0 0', fontSize: '1rem' }}>{activeJourney.summary}</p>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: '0.875rem', color: 'var(--secondary)', display: 'block' }}>Primary Actor:</span>
            <strong style={{ color: 'var(--teal)', fontSize: '0.95rem' }}>{activeJourney.actor}</strong>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)', gap: '28px' }}>
          <div>
            <h3 style={{ fontSize: '1.1rem', marginBottom: '12px' }}>Operational Walkthrough</h3>
            <p style={{ color: 'var(--text)', lineHeight: 1.7, fontSize: '0.95rem', marginBottom: '20px' }}>
              {activeJourney.deepDive}
            </p>

            <h3 style={{ fontSize: '1.1rem', marginBottom: '12px' }}>Mandatory Constraints Enforced</h3>
            <ul style={{ paddingLeft: '20px', color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.8 }}>
              {activeJourney.constraints.map((c, i) => (
                <li key={i}><strong style={{ color: 'var(--text)' }}>{c}</strong></li>
              ))}
            </ul>
          </div>

          <div style={{ background: 'var(--bg)', padding: '20px', borderRadius: '12px', border: '1px solid var(--border)' }}>
            <h3 style={{ fontSize: '1.05rem', marginBottom: '14px', color: 'var(--amber)' }}>AWS Architecture Stack</h3>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '20px' }}>
              {activeJourney.awsServices.map(svc => (
                <span key={svc} className="badge badge-published" style={{ fontSize: '0.8rem', padding: '4px 8px' }}>
                  {svc}
                </span>
              ))}
            </div>

            <h3 style={{ fontSize: '1.05rem', marginBottom: '8px', color: 'var(--teal)' }}>Verified Artifact Produced</h3>
            <p style={{ fontFamily: 'ui-monospace, monospace', fontSize: '0.82rem', background: 'var(--panel)', padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border)', color: 'var(--text)' }}>
              {activeJourney.artifactProduced}
            </p>

            <div style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid var(--border)' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--secondary)', display: 'block', marginBottom: '8px' }}>
                Ready to test this journey live?
              </span>
              <a href={routeLink('/workspace')} className="button" style={{ width: '100%', textAlign: 'center' }}>
                Test in Community Workspace →
              </a>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
