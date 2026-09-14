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
    title: 'Intake',
    summary: 'A donor or the coordinator types the offer. Merismos refuses personal data and instruction-like text at the door, names what it refused, and marks the field when it can match it.',
    actor: 'Donor or coordinator typing the offer',
    timeToComplete: 'a form',
    constraints: [
      'Personal data is refused: phone numbers, IBANs, card numbers, national IDs, named households',
      'Instruction-like text is refused; donor and organisation names are carried as untrusted text',
      'Use-by must not be before the collection date',
      'A chilled or frozen offer must say how many hours it has been out of the fridge; without that figure it is refused',
    ],
    awsServices: ['Amazon API Gateway HTTP API', 'AWS Lambda', 'Workspace session: DynamoDB in AWS, SQLite in CI'],
    artifactProduced: 'The offer JSON: title, donor, quantity + unit, category (ambient / chilled / frozen), collection date, use-by, hours unrefrigerated, allergens, manifest, note',
    deepDive: 'The intake form takes the fields above and nothing else. If a field contains a phone number, an IBAN, a card number, a national ID, a named household, or text that reads like an instruction, the offer is refused, the response names what it refused, and the form marks the field when it can match it. Donor and organisation names are carried as untrusted text, not as instructions.',
  },
  {
    id: 'checks',
    number: '02',
    title: 'The checks',
    summary: 'Four Strands specialists read the network’s registers through bounded tools; a guard cancels anything outside the corpus; a bounded solver proposes the split.',
    actor: 'Four Strands specialists (food safety, capacity, equity, premises) and the guard',
    timeToComplete: 'not measured',
    constraints: [
      'Storage is a veto',
      'Transport is a cap',
      'The network’s 40% ceiling is network policy, not a universal or certified fairness definition',
      'Food-safety refusals are final: a broken cold chain is refused in full, never reduced',
      'A block that turns on something changeable is parked with a reason and a one-shot wake',
    ],
    awsServices: ['Strands Agents SDK', 'AWS Lambda', 'Amazon Bedrock (live mode only)', 'Scripted planner (sandbox and CI)'],
    artifactProduced: 'A proposed split: one line per organisation with a reason, plus the stated remainder (what nobody can take)',
    deepDive: 'Each specialist reads the organisations register, the allocation policy, the retention policy and the manifests through bounded read-only tools with a budget of distinct paths. A BeforeToolCallEvent hook cancels any tool call outside the allowed corpus; the swap test shows the demo stops when the SDK is replaced. A deterministic gate checks the draft record for personal data before it can be approved. In the sandbox the model is scripted-planner/1.0.0: a real Strands agent loop with scripted responses and no Bedrock call. In live mode the model is Amazon Bedrock.',
  },
  {
    id: 'approval',
    number: '03',
    title: 'Human approval',
    summary: 'A person approves the exact plan, or does not. Approval is consent to the exact record digest and address.',
    actor: 'The network coordinator',
    timeToComplete: 'one explicit consent',
    constraints: [
      'Consent is to the exact record digest and address',
      'A stale plan is refused',
      'Sandbox approval records the decision inside the isolated session and publishes nothing',
      'Live approval needs the network-coordinator grant (merismos:coordinate) in the API Gateway authorizer context; no authorizer is deployed on the public API, so public writes are refused, and no header or body value can confer the grant',
    ],
    awsServices: ['AWS Lambda', 'Amazon DynamoDB (thread, approvals)', 'Amazon S3 records bucket (live mode)'],
    artifactProduced: 'An approval entry in the append-only ledger; in live mode, a Markdown record at a stable public address',
    deepDive: 'The coordinator sees every line and its reason before approving. Approval names the record digest and address it applies to; if the plan has changed since, the approval is refused. In the public sandbox the decision is recorded inside the session and nothing is published. In live mode the writer Lambda, whose role is the only one of the three fleet roles with s3:PutObject on the records bucket, publishes a Markdown record there. Corrections are new records at the next address that name what they replaced; the superseded record stays served with a notice.',
  },
  {
    id: 'collection',
    number: '04',
    title: 'Collection',
    summary: 'A claim, an agreed time and an explicit “collection confirmed” are three separate recorded facts. Merismos sends nothing.',
    actor: 'The organisation’s collector and the coordinator',
    timeToComplete: 'three separate facts',
    constraints: [
      'A claim, an agreed time and an explicit confirmation are three separate recorded facts',
      'No message, notification or email is sent by Merismos',
      'No vehicle is dispatched and there is no departure event',
      'A no-show can only be recorded after the agreed time has passed',
    ],
    awsServices: ['Amazon DynamoDB thread ledger', 'Amazon EventBridge Scheduler (parked decisions)', 'Amazon SQS dead-letter queue (wakes)'],
    artifactProduced: '`pickup.claimed` and `pickup.confirmed` entries in the thread ledger',
    deepDive: 'Collection is recorded, not inferred. An organisation claims its share; a collection time is agreed; someone explicitly confirms that the food was collected. Each is its own ledger entry with a body digest and a parent link, and the custody summary reports what it cannot see. Decisions parked on something changeable get a one-shot EventBridge Scheduler wake, with an SQS dead-letter queue for wakes that fail.',
  },
];

export function UserJourneysView({ data }: UserJourneysViewProps) {
  const [selectedId, setSelectedId] = useState('intake');
  const activeJourney = JOURNEYS.find(j => j.id === selectedId) || JOURNEYS[0];

  return (
    <div className="journeys-view" style={{ maxWidth: '1280px', margin: '0 auto', padding: '16px 0 48px' }}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">FROM OFFER TO COLLECTION</p>
          <h1>How a donation moves through Merismos</h1>
          <p>Intake, the checks, human approval and collection: what each stage records and what it refuses.</p>
        </div>
        <a className="button" href={routeLink('/workspace')}>
          Open the workspace →
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
            <span className="eyebrow">STAGE {activeJourney.number}</span>
            <h2 id="active-journey-title" style={{ fontSize: '1.6rem', marginTop: '4px' }}>{activeJourney.title}</h2>
            <p style={{ color: 'var(--secondary)', margin: '4px 0 0', fontSize: '1rem' }}>{activeJourney.summary}</p>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: '0.875rem', color: 'var(--secondary)', display: 'block' }}>Who acts:</span>
            <strong style={{ color: 'var(--teal)', fontSize: '0.95rem' }}>{activeJourney.actor}</strong>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)', gap: '28px' }}>
          <div>
            <h3 style={{ fontSize: '1.1rem', marginBottom: '12px' }}>What happens</h3>
            <p style={{ color: 'var(--text)', lineHeight: 1.7, fontSize: '0.95rem', marginBottom: '20px' }}>
              {activeJourney.deepDive}
            </p>

            <h3 style={{ fontSize: '1.1rem', marginBottom: '12px' }}>Rules enforced</h3>
            <ul style={{ paddingLeft: '20px', color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.8 }}>
              {activeJourney.constraints.map((c, i) => (
                <li key={i}><strong style={{ color: 'var(--text)' }}>{c}</strong></li>
              ))}
            </ul>
          </div>

          <div style={{ background: 'var(--bg)', padding: '20px', borderRadius: '12px', border: '1px solid var(--border)' }}>
            <h3 style={{ fontSize: '1.05rem', marginBottom: '14px', color: 'var(--amber)' }}>What runs here</h3>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '20px' }}>
              {activeJourney.awsServices.map(svc => (
                <span key={svc} className="badge badge-published" style={{ fontSize: '0.8rem', padding: '4px 8px' }}>
                  {svc}
                </span>
              ))}
            </div>

            <h3 style={{ fontSize: '1.05rem', marginBottom: '8px', color: 'var(--teal)' }}>What is recorded</h3>
            <p style={{ fontFamily: 'ui-monospace, monospace', fontSize: '0.82rem', background: 'var(--panel)', padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border)', color: 'var(--text)' }}>
              {activeJourney.artifactProduced}
            </p>

            <div style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid var(--border)' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--secondary)', display: 'block', marginBottom: '8px' }}>
                {data ? `Try this stage in the ${data.mode === 'sandbox' ? 'sandbox' : 'live workspace'} (${data.network}).` : 'Try this stage in the workspace.'}
              </span>
              <a href={routeLink('/workspace')} className="button" style={{ width: '100%', textAlign: 'center' }}>
                Open the workspace →
              </a>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
