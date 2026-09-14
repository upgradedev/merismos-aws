import { routeLink } from './routes';

const DEMONSTRATED: string[] = [
  'Intake that refuses personal data (phone numbers, email addresses, street addresses, IBANs, card numbers, national IDs, named households) and instruction-like text, names what it refused, and marks the field when it can match it.',
  'Up to four specialists apply deterministic rules first. Where those rules do not already refuse, the specialist runs as a Strands agent through bounded read-only tools, with a guard that cancels calls outside the corpus.',
  'A bounded solver: storage is a veto, transport is a cap, the network’s 40% ceiling is its own policy, and what nobody can take is stated as a remainder.',
  'A broken cold chain refused in full, with the reason. A changeable block is parked with a reason; this sandbox uses no scheduler and creates no wake.',
  'A person approving the exact plan: consent to the exact record digest and address. In the sandbox, nothing is published.',
  'A versioned sandbox workspace snapshot. The separate live run ledger appends digest-linked entries, and published corrections use new record addresses.',
  'A claim and explicit confirmation stored separately, with an optional agreed time that can be replaced before confirmation. No message is sent; no vehicle is dispatched.',
];

const NOT_MEASURED: { label: string; note: string }[] = [
  { label: 'Human time saved', note: 'Unknown until measured.' },
  { label: 'Food rescued', note: 'Unknown until measured.' },
  { label: 'Beneficiaries reached', note: 'Unknown until measured.' },
];

const HISTORICAL_TECHNICAL = [
  { label: 'Scripted sandbox request', note: 'At frontend and backend commit cb97c9e, one workstation sent 10 samples on 2026-09-13. The run request median was 426 ms and the maximum was 2,628 ms. This is historical, not a frozen-release measurement or a load test; live Bedrock latency is not measured.' },
  { label: 'Deploy-proof pricing', note: 'The repository documents a historical ESTIMATE for Bedrock tokens and Lambda only. It is not total AWS cost or an invoice, and the raw cost rows are not published, so no dollar figure is shown here.' },
];

export function GtmImpactView() {
  return (
    <div className="gtm-impact-view" style={{ maxWidth: '1280px', margin: '0 auto', padding: '16px 0 48px' }}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">GOOD NEIGHBOR AGENTS · IMPACT &amp; LIMITS</p>
          <h1>Impact and limits</h1>
          <p>What this sandbox demonstrates, what it does not measure, and what is still an open question.</p>
        </div>
        <a className="button" href={routeLink('/dashboard')}>
          Open the dashboard →
        </a>
      </div>

      {/* The problem */}
      <section className="panel padded coordinator-start" style={{ marginBottom: '28px' }}>
        <h2 style={{ fontSize: '1.4rem', color: 'var(--text)', marginBottom: '16px' }}>The coordination and trust problem</h2>
        <p style={{ color: 'var(--text)', fontSize: '1.05rem', lineHeight: 1.6, maxWidth: '850px' }}>
          A surplus-food offer arrives with a use-by date and a collection date, and a volunteer coordinator has to decide who can take it safely, who has the storage and transport, and whether the split follows the network’s own policy.
          In an informal group chat or phone workflow, reasons may be scattered or omitted. Merismos keeps the computed reasons beside the coordinator’s decision; no comparative user study has been run.
        </p>
      </section>

      {/* Demonstrated / not measured */}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px', marginBottom: '28px' }}>
        <div className="panel padded" style={{ margin: 0 }}>
          <p className="eyebrow">WHAT THIS SANDBOX DEMONSTRATES</p>
          <ul style={{ paddingLeft: '20px', color: 'var(--text)', fontSize: '0.95rem', lineHeight: 1.7, margin: '8px 0 0' }}>
            {DEMONSTRATED.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </div>
        <div className="panel padded" style={{ margin: 0 }}>
          <p className="eyebrow">WHAT IS NOT MEASURED</p>
          <dl className="facts" style={{ marginTop: '8px' }}>
            {NOT_MEASURED.map(item => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.note}</dd>
              </div>
            ))}
          </dl>
          <p className="small-note" style={{ marginTop: '12px' }}>
            No benefit number is inferred. The sandbox uses synthetic offers and organisations.
          </p>
        </div>
      </section>

      <section className="panel padded" style={{ marginBottom: '28px' }}>
        <p className="eyebrow">HISTORICAL TECHNICAL OBSERVATIONS</p>
        <dl className="facts" style={{ marginTop: '8px' }}>
          {HISTORICAL_TECHNICAL.map(item => <div key={item.label}><dt>{item.label}</dt><dd>{item.note}</dd></div>)}
        </dl>
      </section>

      {/* Coordination methods compared */}
      <section className="panel padded" style={{ marginBottom: '28px' }}>
        <div className="section-heading">
          <div>
            <p className="eyebrow">COORDINATION METHODS</p>
            <h2 style={{ fontSize: '1.4rem' }}>How the decision is made today, and what changes</h2>
          </div>
        </div>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col" style={{ width: '20%' }}>Method</th>
                <th scope="col" style={{ width: '26%' }}>How it works</th>
                <th scope="col" style={{ width: '27%' }}>Where it breaks</th>
                <th scope="col" style={{ width: '27%' }}>What Merismos changes</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Group chat or phone tree</strong></td>
                <td>The coordinator posts or calls; some informal workflows may prioritize the first available reply.</td>
                <td>Decision reasons can be scattered, omitted or hard to revisit. This is a general comparison, not a study of a named tool.</td>
                <td>A reason on every line, food-safety refusals that are final and explained, and a versioned decision snapshot before anything is collected.</td>
              </tr>
              <tr>
                <td><strong>A spreadsheet</strong></td>
                <td>The coordinator keeps a sheet of members, capacities and past allocations and fills in each offer by hand.</td>
                <td>Capacity and premises rules are applied by hand; a cell can be edited after the fact; nothing checks the entry for personal data.</td>
                <td>The registers are read by the specialists through bounded tools; a deterministic gate checks the draft for personal data; corrections are new records, not edits.</td>
              </tr>
              <tr>
                <td><strong>Merismos</strong></td>
                <td>Intake, up to four rule-first specialist checks, a bounded solver, human approval of the exact plan, separate claim and confirmation, and an optional agreed time.</td>
                <td>It is a sandbox with synthetic data. Time saved, food rescued and total AWS cost are not measured. It sends no messages, so the coordinator still has to talk to people.</td>
                <td>Nothing is automated past the record: no message, no dispatch. What it adds is the kept reason and the recorded decision.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Operating model */}
      <section className="panel padded" style={{ background: 'var(--panel)' }}>
        <div className="section-heading">
          <div>
            <p className="eyebrow">OPERATING MODEL</p>
            <h2 style={{ fontSize: '1.4rem' }}>Open questions</h2>
          </div>
        </div>
        <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', lineHeight: 1.6, maxWidth: '850px', margin: 0 }}>
          Who would run Merismos for a real network, and how it would be funded, are open questions that this sandbox does not answer: it demonstrates the mechanism, not an operation.
        </p>
      </section>
    </div>
  );
}
