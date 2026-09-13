import { routeLink } from './routes';

export function GtmImpactView() {
  return (
    <div className="gtm-impact-view" style={{ maxWidth: '1280px', margin: '0 auto', padding: '16px 0 48px' }}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">GOOD NEIGHBOR TRACK · GTM & CIVIC IMPACT</p>
          <h1>Civic Impact & Operational Economics</h1>
          <p>Why Merismos replaces informal WhatsApp coordination with zero-overhead serverless fairness.</p>
        </div>
        <a className="button" href={routeLink('/dashboard')}>
          Launch Cockpit →
        </a>
      </div>

      {/* Top Metrics Banner */}
      <section className="panel padded coordinator-start" style={{ marginBottom: '28px' }}>
        <h2 style={{ fontSize: '1.4rem', color: 'var(--text)', marginBottom: '16px' }}>The Civic Coordination Bottleneck</h2>
        <p style={{ color: 'var(--text)', fontSize: '1.05rem', lineHeight: 1.6, maxWidth: '850px' }}>
          In urban neighborhoods like Kypseli, food waste is not an inventory problem; it is a <strong>coordination and trust bottleneck</strong>.
          Supermarkets discard surplus because calling five separate charities within a 2-hour window is impossible for retail workers.
          Meanwhile, volunteer coordinators burn out from answering dozens of emergency calls, often facing community accusations of favoritism.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', marginTop: '24px' }}>
          <div style={{ background: 'var(--bg)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--secondary)', textTransform: 'uppercase' }}>TIME SAVED PER OFFER</span>
            <strong style={{ display: 'block', fontSize: '1.8rem', color: 'var(--teal)', margin: '4px 0' }}>45 Minutes</strong>
            <small style={{ color: 'var(--secondary)' }}>Replaces 15-25 manual calls and messages.</small>
          </div>
          <div style={{ background: 'var(--bg)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--secondary)', textTransform: 'uppercase' }}>INFRASTRUCTURE RUN COST</span>
            <strong style={{ display: 'block', fontSize: '1.8rem', color: 'var(--amber)', margin: '4px 0' }}>$0.0004</strong>
            <small style={{ color: 'var(--secondary)' }}>Per completed allocation run on AWS Lambda.</small>
          </div>
          <div style={{ background: 'var(--bg)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--secondary)', textTransform: 'uppercase' }}>COMMUNITY TRUST</span>
            <strong style={{ display: 'block', fontSize: '1.8rem', color: '#60a5fa', margin: '4px 0' }}>100% Non-Repudiation</strong>
            <small style={{ color: 'var(--secondary)' }}>Immutable audit trails hosted publicly on S3.</small>
          </div>
        </div>
      </section>

      {/* Head-to-Head Comparison Matrix */}
      <section className="panel padded" style={{ marginBottom: '28px' }}>
        <div className="section-heading">
          <div>
            <p className="eyebrow">MARKET DIFFERENTIATION</p>
            <h2 style={{ fontSize: '1.4rem' }}>What Merismos Replaces</h2>
          </div>
        </div>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col" style={{ width: '25%' }}>Method / Tool</th>
                <th scope="col" style={{ width: '25%' }}>How It Operates</th>
                <th scope="col" style={{ width: '25%' }}>Why It Fails</th>
                <th scope="col" style={{ width: '25%' }}>Merismos Advantage</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>WhatsApp & Phone Trees</strong></td>
                <td>Coordinator broadcasts offers to a group chat; first to reply claims the food.</td>
                <td>First-come-first-served creates hoarding. Large shelters take everything; smaller community kitchens get starved.</td>
                <td><strong style={{ color: 'var(--teal)' }}>Algorithmic Fair-Share:</strong> Tracks past allocations and enforces equity quotas.</td>
              </tr>
              <tr>
                <td><strong>Enterprise NGO Software</strong></td>
                <td>Centralized platforms requiring dedicated dispatchers and annual software licenses ($3,000-$10,000/year).</td>
                <td>Far too expensive and rigid for small grassroots volunteer groups operating on zero IT budget.</td>
                <td><strong style={{ color: 'var(--teal)' }}>Serverless Pay-Per-Use:</strong> Runs for pennies a month with zero upfront capital cost.</td>
              </tr>
              <tr>
                <td><strong>Consumer Apps (Too Good To Go)</strong></td>
                <td>Consumers purchase surplus meals at a discount directly from restaurants.</td>
                <td>Commercialized D2C model does not serve vulnerable populations, soup kitchens, or bulk pallet donations.</td>
                <td><strong style={{ color: 'var(--teal)' }}>Institutional Civic Focus:</strong> Routes bulk surplus directly to non-profit shelters.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Target Persona & Expansion Strategy */}
      <section className="panel padded" style={{ background: 'var(--panel)' }}>
        <div className="section-heading">
          <div>
            <p className="eyebrow">GO-TO-MARKET & DEPLOYMENT POSTURE</p>
            <h2 style={{ fontSize: '1.4rem' }}>Target Personas & Municipal Deployment (B2G)</h2>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '20px' }}>
          <div style={{ background: 'var(--bg)', padding: '20px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <h3 style={{ fontSize: '1.1rem', color: 'var(--teal)', margin: '0 0 8px' }}>Grassroots Volunteer Coordinator</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.6 }}>
              Elena, coordinating 5 neighborhood initiatives in central Athens. Operates out of a smartphone between work shifts.
              Needs an interface that requires zero training, validates food safety rules automatically, and outputs ready-to-share summaries for volunteer drivers.
            </p>
          </div>

          <div style={{ background: 'var(--bg)', padding: '20px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <h3 style={{ fontSize: '1.1rem', color: 'var(--amber)', margin: '0 0 8px' }}>Municipal Social Solidarity Services (B2G)</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.6 }}>
              City councils and regional social service departments seeking to reduce landfill organic waste under EU Green Deal directives.
              Merismos provides municipalities with auditable, compliant reporting on diverted food tonnage without demanding full-time staff overhead.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
