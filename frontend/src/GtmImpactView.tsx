import { routeLink } from './routes';

const DEMONSTRATED: string[] = [
  'Intake that refuses personal data (phone numbers, IBANs, card numbers, national IDs, named households) and instruction-like text, and says which field was refused.',
  'Four Strands specialists (food safety, capacity, equity, premises) reading the network’s registers through bounded read-only tools, with a guard that cancels any tool call outside the corpus.',
  'A bounded solver: storage is a veto, transport is a cap, the network’s 40% ceiling is its own policy, and what nobody can take is stated as a remainder.',
  'A broken cold chain refused in full, with the reason. Blocks that turn on something changeable are parked with a reason and a one-shot wake.',
  'A person approving the exact plan: consent to the exact record digest and address. In the sandbox, nothing is published.',
  'An append-only ledger where each entry carries a body digest and a parent link, and where a correction is a new record that names what it replaced.',
  'A claim, an agreed time and an explicit “collection confirmed” recorded as three separate facts. No message is sent; no vehicle is dispatched.',
];

const NOT_MEASURED: { label: string; note: string }[] = [
  { label: 'Human time saved', note: 'Unknown until measured.' },
  { label: 'Food rescued', note: 'Unknown until measured.' },
  { label: 'Beneficiaries reached', note: 'Unknown until measured.' },
  { label: 'AWS cost per run', note: 'Unknown until measured. See Cost and sustainability in the README.' },
  { label: 'Latency on AWS', note: 'Unknown until measured. The sandbox runs a scripted planner; its timings are not AWS timings.' },
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
          A surplus-food offer arrives with a use-by date and a collection date, and a volunteer coordinator has to decide who can take it safely, who has the storage and the transport, and whether the split is fair under the network’s own policy.
          Made in a group chat or by phone, that decision leaves no record of its reasons, and the coordinator alone answers for it.
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
            Any number for these would be invented. The sandbox uses synthetic offers and organisations.
          </p>
        </div>
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
                <td>The coordinator posts or calls; whoever answers first takes the food.</td>
                <td>No record of why; a chilled offer is accepted or refused on the spot; the coordinator alone answers for the split.</td>
                <td>A reason on every line, food-safety refusals that are final and explained, and an append-only record of the decision before anything is collected.</td>
              </tr>
              <tr>
                <td><strong>A spreadsheet</strong></td>
                <td>The coordinator keeps a sheet of members, capacities and past allocations and fills in each offer by hand.</td>
                <td>Capacity and premises rules are applied by hand; a cell can be edited after the fact; nothing checks the entry for personal data.</td>
                <td>The registers are read by the specialists through bounded tools; a deterministic gate checks the draft for personal data; corrections are new records, not edits.</td>
              </tr>
              <tr>
                <td><strong>Merismos</strong></td>
                <td>Intake, four specialist checks, a bounded solver, human approval of the exact plan, and three separately recorded collection facts.</td>
                <td>It is a sandbox with synthetic data. Time saved, food rescued and cost per run are not measured. It sends no messages, so the coordinator still has to talk to people.</td>
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
