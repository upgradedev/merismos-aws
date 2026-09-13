import { routeLink } from './routes';
import type { Workspace } from './types';

interface LandingPageProps {
  data?: Workspace;
  onLaunchCockpit?: () => void;
}

export function LandingPage({ data, onLaunchCockpit }: LandingPageProps) {
  const sampleOffer = data?.offers[0]?.offer;
  const launchHref = routeLink('/dashboard');

  return (
    <div className="landing-container" style={{ maxWidth: '1280px', margin: '0 auto', padding: '24px 16px 64px' }}>
      {/* Hero Section */}
      <section className="panel padded coordinator-start" style={{ padding: '48px 36px', marginBottom: '32px' }} aria-labelledby="landing-hero-title">
        <p className="eyebrow" style={{ textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700 }}>
          GOOD NEIGHBOR AGENTS · CIVIC SURPLUS APPORTIONMENT
        </p>
        <h1 id="landing-hero-title" style={{ fontSize: 'clamp(2rem, 4vw, 3.2rem)', fontWeight: 800, lineHeight: 1.15, margin: '12px 0 18px', color: 'var(--text)' }}>
          Fair food surplus allocation <br />
          <span style={{ color: 'var(--teal)' }}>before the clock runs out.</span>
        </h1>
        <p style={{ fontSize: '1.2rem', lineHeight: 1.6, color: 'var(--text)', maxWidth: '780px', marginBottom: '28px' }}>
          When a local supermarket offers 200 kg of fresh food expiring tomorrow, volunteer coordinators face 20 frantic phone calls and accusations of favoritism.
          <strong> Merismos</strong> arbitrates multi-agent constraints in seconds, ensures equitable distribution across community shelters, and seals every allocation in a tamper-evident public audit log.
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'center' }}>
          <a
            href={launchHref}
            onClick={onLaunchCockpit}
            className="button"
            data-testid="landing-launch-cockpit"
            style={{ fontSize: '1.05rem', padding: '14px 28px', background: 'var(--teal)', color: '#0c2527', textDecoration: 'none', fontWeight: 700 }}
          >
            Launch Operations Cockpit →
          </a>
          <a
            href="#/journeys"
            className="button secondary"
            style={{ fontSize: '1.05rem', padding: '14px 24px', textDecoration: 'none' }}
          >
            Explore User Journeys
          </a>
          <a
            href="#/architecture"
            className="button secondary"
            style={{ fontSize: '1.05rem', padding: '14px 24px', textDecoration: 'none' }}
          >
            AWS Architecture
          </a>
        </div>
        <p className="small-note" style={{ marginTop: '20px', color: 'var(--secondary)' }}>
          100% anonymous browser execution · No login, no credit card, no install required · Zero-footprint serverless demo.
        </p>
      </section>

      {/* 3 Value Metrics Grid */}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', marginBottom: '36px' }}>
        <div className="panel padded" style={{ margin: 0 }}>
          <span className="eyebrow">EQUITY IN RECOVERY</span>
          <strong style={{ display: 'block', fontSize: '2.2rem', margin: '8px 0', color: 'var(--teal)' }}>5 Shelters</strong>
          <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', margin: 0 }}>
            Apportions surplus across St. Panteleimon Soup Kitchen, Kypseli Homeless Shelter, Refugee Solidarity Center, Elderly Care, and Youth Hub without bias.
          </p>
        </div>
        <div className="panel padded" style={{ margin: 0 }}>
          <span className="eyebrow">COLD CHAIN & REFRIGERATION</span>
          <strong style={{ display: 'block', fontSize: '2.2rem', margin: '8px 0', color: 'var(--amber)' }}>0 Refusal Leaks</strong>
          <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', margin: 0 }}>
            Strict constraints ensure perishable chilled dairy or meat is never routed to facilities lacking refrigeration capacity or transport.
          </p>
        </div>
        <div className="panel padded" style={{ margin: 0 }}>
          <span className="eyebrow">NON-REPUDIATION AUDIT</span>
          <strong style={{ display: 'block', fontSize: '2.2rem', margin: '8px 0', color: 'var(--text)' }}>S3 Proof Ledger</strong>
          <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', margin: 0 }}>
            Every allocation decision is cryptographically signed and published to a public Amazon S3 bucket, preventing backroom favoritism.
          </p>
        </div>
      </section>

      {/* How It Works: 3 Steps */}
      <section className="panel padded" style={{ marginBottom: '36px' }}>
        <div className="section-heading" style={{ marginBottom: '24px' }}>
          <div>
            <p className="eyebrow">HOW MERISMOS WORKS</p>
            <h2 style={{ fontSize: '1.6rem' }}>From supermarket surplus to verified shelter delivery in 3 steps</h2>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '24px' }}>
          <div style={{ borderTop: '2px solid var(--teal)', paddingTop: '16px' }}>
            <span style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--teal)' }}>01</span>
            <h3 style={{ margin: '8px 0', fontSize: '1.15rem' }}>Donation Intake & Profiling</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.6 }}>
              A donor (supermarket, bakery, market) logs available quantity, expiry date, and thermal storage requirements (ambient, chilled, frozen).
            </p>
          </div>
          <div style={{ borderTop: '2px solid var(--amber)', paddingTop: '16px' }}>
            <span style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--amber)' }}>02</span>
            <h3 style={{ margin: '8px 0', fontSize: '1.15rem' }}>Multi-Agent Equity Arbitration</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.6 }}>
              AWS Strands Agents negotiate constraints: distance to donor, current inventory, volunteer availability, and historical fair-share index.
            </p>
          </div>
          <div style={{ borderTop: '2px solid #60a5fa', paddingTop: '16px' }}>
            <span style={{ fontSize: '1.8rem', fontWeight: 800, color: '#60a5fa' }}>03</span>
            <h3 style={{ margin: '8px 0', fontSize: '1.15rem' }}>Return-of-Control & Public Proof</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.6 }}>
              The volunteer coordinator reviews the exact plan with full rationale. Upon human sign-off, dispatch notices fire and the immutable proof is saved to S3.
            </p>
          </div>
        </div>
      </section>

      {/* Live Sample Showcase */}
      <section className="panel padded" style={{ marginBottom: '36px', background: 'var(--raised)' }}>
        <div className="section-heading">
          <div>
            <p className="eyebrow">CURRENT SAMPLE SCENARIO</p>
            <h2 style={{ fontSize: '1.4rem' }}>
              {sampleOffer ? `${sampleOffer.title} (${sampleOffer.quantity} ${sampleOffer.unit})` : 'Kypseli Food Rescue Scenario'}
            </h2>
          </div>
          <a href="#/workspace" className="button" style={{ fontSize: '0.875rem' }}>Open in Workspace →</a>
        </div>
        <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', maxWidth: '800px', marginBottom: '20px' }}>
          Donor: <strong>{sampleOffer?.donor || 'Metro Cash & Carry Kypseli'}</strong> · Collection window: <strong>Today before 18:00</strong>.
          The allocation engine accounts for the same-day constraint and balances needs between high-capacity soup kitchens and smaller shelters.
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
          <span className="badge badge-published">100% Traceable</span>
          <span className="badge badge-confirmed">Multi-Agent Arbitrated</span>
          <span className="badge badge-running">AWS Strands Native</span>
          <span className="badge badge-scheduled">Amazon Bedrock Grounded</span>
        </div>
      </section>

      {/* Footer / Disclaimer */}
      <footer style={{ borderTop: '1px solid var(--border)', paddingTop: '20px', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px', color: 'var(--secondary)', fontSize: '0.875rem' }}>
        <span>Merismos (μερισμός): Apportionment of one thing among several.</span>
        <div>
          <a href="#/impact" style={{ marginRight: '16px' }}>Social Impact & GTM</a>
          <a href="#/architecture" style={{ marginRight: '16px' }}>System Architecture</a>
          <a href="#/records">Public S3 Records</a>
        </div>
      </footer>
    </div>
  );
}
