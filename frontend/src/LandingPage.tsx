import { routeLink } from './routes';
import type { Workspace } from './types';

interface LandingPageProps {
  data?: Workspace;
  onLaunchCockpit?: () => void;
  onNavigate?: (route: string) => void;
}

export function LandingPage({ data, onLaunchCockpit, onNavigate }: LandingPageProps) {
  const sampleOffer = data?.offers[0]?.offer;
  const launchHref = routeLink('/dashboard');

  const handleNav = (path: string, fallbackAction?: () => void) => (e: React.MouseEvent) => {
    if (fallbackAction) fallbackAction();
    if (onNavigate) {
      e.preventDefault();
      onNavigate(path);
    }
  };

  return (
    <div className="landing-container" style={{ maxWidth: '1280px', margin: '0 auto', padding: '24px 16px 64px' }}>
      {/* Hero Section */}
      <section
        className="panel padded coordinator-start"
        style={{
          padding: '52px 40px',
          marginBottom: '32px',
          position: 'relative',
          overflow: 'hidden',
          background: 'linear-gradient(135deg, rgba(20, 26, 46, 0.95) 0%, rgba(22, 50, 57, 0.85) 100%)',
          backdropFilter: 'blur(16px)',
          border: '1px solid #3c746e',
          boxShadow: '0 12px 40px -10px rgba(113, 222, 205, 0.15)',
        }}
        aria-labelledby="landing-hero-title"
      >
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 14px', borderRadius: '999px', background: 'rgba(113, 222, 205, 0.12)', border: '1px solid #3c746e', marginBottom: '16px' }}>
          <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#4ade80', boxShadow: '0 0 8px #4ade80' }} />
          <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--teal)', letterSpacing: '0.06em' }}>
            LIVE CIVIC DISPATCH ENGINE · KYPSELI NETWORK
          </span>
        </div>

        <p className="eyebrow" style={{ textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700 }}>
          GOOD NEIGHBOR AGENTS · CIVIC SURPLUS APPORTIONMENT
        </p>
        <h1 id="landing-hero-title" style={{ fontSize: 'clamp(2.1rem, 4.2vw, 3.4rem)', fontWeight: 800, lineHeight: 1.15, margin: '12px 0 18px', color: 'var(--text)' }}>
          Fair food surplus allocation <br />
          <span style={{ color: 'var(--teal)', textShadow: '0 0 24px rgba(113,222,205,0.3)' }}>before the clock runs out.</span>
        </h1>
        <p style={{ fontSize: '1.2rem', lineHeight: 1.6, color: 'var(--text)', maxWidth: '820px', marginBottom: '32px' }}>
          When a local supermarket offers 200 kg of fresh food expiring tomorrow, volunteer coordinators face 20 frantic phone calls and accusations of favoritism.
          <strong> Merismos</strong> arbitrates multi-agent constraints in seconds, ensures equitable distribution across community shelters, and seals every allocation in a tamper-evident public audit log.
        </p>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'center' }}>
          <a
            href={launchHref}
            onClick={handleNav('/dashboard', onLaunchCockpit)}
            className="button"
            data-testid="landing-launch-cockpit"
            style={{ fontSize: '1.05rem', padding: '14px 30px', background: 'var(--teal)', color: '#0c2527', textDecoration: 'none', fontWeight: 700, borderRadius: '10px', boxShadow: '0 4px 16px rgba(113, 222, 205, 0.3)' }}
          >
            Launch Operations Cockpit →
          </a>
          <a
            href="#/journeys"
            onClick={handleNav('/journeys')}
            className="button secondary"
            style={{ fontSize: '1.05rem', padding: '14px 24px', textDecoration: 'none', borderRadius: '10px' }}
          >
            Explore User Journeys
          </a>
          <a
            href="#/architecture"
            onClick={handleNav('/architecture')}
            className="button secondary"
            style={{ fontSize: '1.05rem', padding: '14px 24px', textDecoration: 'none', borderRadius: '10px' }}
          >
            AWS Architecture
          </a>
          <a
            href="#/impact"
            onClick={handleNav('/impact')}
            className="button secondary"
            style={{ fontSize: '1.05rem', padding: '14px 24px', textDecoration: 'none', borderRadius: '10px' }}
          >
            Civic Impact & ROI
          </a>
        </div>

        <p className="small-note" style={{ marginTop: '24px', color: 'var(--secondary)' }}>
          100% anonymous browser execution · No login, no credit card, no install required · Zero-footprint serverless demo.
        </p>
      </section>

      {/* 3 Value Metrics Grid */}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', marginBottom: '36px' }}>
        <div className="panel padded" style={{ margin: 0, background: 'rgba(20, 26, 46, 0.85)', border: '1px solid var(--border)', borderRadius: '14px', backdropFilter: 'blur(10px)' }}>
          <span className="eyebrow">EQUITY IN RECOVERY</span>
          <strong style={{ display: 'block', fontSize: '2.4rem', margin: '8px 0', color: 'var(--teal)' }}>5 Shelters</strong>
          <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', margin: 0 }}>
            Apportions surplus across St. Panteleimon Soup Kitchen, Kypseli Homeless Shelter, Refugee Solidarity Center, Elderly Care, and Youth Hub without bias.
          </p>
        </div>
        <div className="panel padded" style={{ margin: 0, background: 'rgba(20, 26, 46, 0.85)', border: '1px solid var(--border)', borderRadius: '14px', backdropFilter: 'blur(10px)' }}>
          <span className="eyebrow">COLD CHAIN & REFRIGERATION</span>
          <strong style={{ display: 'block', fontSize: '2.4rem', margin: '8px 0', color: 'var(--amber)' }}>0 Refusal Leaks</strong>
          <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', margin: 0 }}>
            Strict constraints ensure perishable chilled dairy or meat is never routed to facilities lacking refrigeration capacity or transport.
          </p>
        </div>
        <div className="panel padded" style={{ margin: 0, background: 'rgba(20, 26, 46, 0.85)', border: '1px solid var(--border)', borderRadius: '14px', backdropFilter: 'blur(10px)' }}>
          <span className="eyebrow">NON-REPUDIATION AUDIT</span>
          <strong style={{ display: 'block', fontSize: '2.4rem', margin: '8px 0', color: 'var(--text)' }}>S3 Proof Ledger</strong>
          <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', margin: 0 }}>
            Every allocation decision is cryptographically signed and published to a public Amazon S3 bucket, preventing backroom favoritism.
          </p>
        </div>
      </section>

      {/* How It Works: 3 Steps */}
      <section className="panel padded" style={{ marginBottom: '36px', background: 'rgba(20, 26, 46, 0.85)', borderRadius: '14px' }}>
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
          <div style={{ borderTop: '2px solid var(--text)', paddingTop: '16px' }}>
            <span style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--text)' }}>03</span>
            <h3 style={{ margin: '8px 0', fontSize: '1.15rem' }}>Return-of-Control & Public Proof</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.6 }}>
              The volunteer coordinator reviews the exact plan with full rationale. Upon human sign-off, dispatch notices fire and the immutable proof is saved to S3.
            </p>
          </div>
        </div>
      </section>

      {/* Interactive Active Scenario Teaser */}
      <section
        className="panel padded"
        style={{
          background: 'linear-gradient(135deg, rgba(23, 42, 53, 0.7) 0%, rgba(20, 26, 46, 0.9) 100%)',
          border: '1px solid #3c746e',
          borderRadius: '14px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
          <div>
            <span className="eyebrow" style={{ color: 'var(--teal)' }}>CURRENT SAMPLE SCENARIO</span>
            <h3 style={{ fontSize: '1.4rem', margin: '6px 0 10px' }}>
              {sampleOffer ? `${sampleOffer.title} (${sampleOffer.quantity} ${sampleOffer.unit})` : 'End of day bread and vegetables (240 kg)'}
            </h3>
            <p style={{ color: 'var(--secondary)', margin: 0, maxWidth: '720px', fontSize: '0.95rem' }}>
              Donor: <strong>{sampleOffer?.donor || 'Neighbourhood bakery and greengrocer, Fokionos Negri'}</strong> · Collection window: <strong>Today before 18:00</strong>.
              The allocation engine accounts for the same-day constraint and balances needs between high-capacity soup kitchens and smaller shelters.
            </p>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '14px' }}>
              <span style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#163239', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #315853' }}>100% Traceable</span>
              <span style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#163239', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #315853' }}>Multi-Agent Arbitrated</span>
              <span style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#163239', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #315853' }}>AWS Strands Native</span>
              <span style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#163239', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #315853' }}>Amazon Bedrock Grounded</span>
            </div>
          </div>
          <a
            href={routeLink('/workspace', { offer: sampleOffer?.id })}
            onClick={handleNav('/workspace')}
            className="button"
            style={{ padding: '12px 24px', whiteSpace: 'nowrap' }}
          >
            Open in Workspace →
          </a>
        </div>
      </section>

      {/* Footer Info */}
      <div style={{ marginTop: '36px', paddingTop: '20px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', fontSize: '0.85rem', color: 'var(--secondary)' }}>
        <span>Merismos (μερισμός): Apportionment of one thing among several.</span>
        <div style={{ display: 'flex', gap: '20px' }}>
          <a href="#/impact" onClick={handleNav('/impact')} style={{ color: 'var(--secondary)' }}>Social Impact & GTM</a>
          <a href="#/architecture" onClick={handleNav('/architecture')} style={{ color: 'var(--secondary)' }}>System Architecture</a>
          <a href="#/records" onClick={handleNav('/records')} style={{ color: 'var(--secondary)' }}>Public S3 Records</a>
        </div>
      </div>
    </div>
  );
}
