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
  const sameDay = !!sampleOffer?.use_by && !!sampleOffer?.collection_date
    && Date.parse(sampleOffer.use_by) - Date.parse(sampleOffer.collection_date) <= 86_400_000;

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
          <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--teal)', letterSpacing: '0.06em' }}>
            SANDBOX · SYNTHETIC DATA · KYPSELI NETWORK
          </span>
        </div>

        <p className="eyebrow" style={{ textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700 }}>
          GOOD NEIGHBOR AGENTS · SURPLUS FOOD APPORTIONMENT
        </p>
        <h1 id="landing-hero-title" style={{ fontSize: 'clamp(2.1rem, 4.2vw, 3.4rem)', fontWeight: 800, lineHeight: 1.15, margin: '12px 0 18px', color: 'var(--text)' }}>
          Fair food surplus allocation, <br />
          <span style={{ color: 'var(--teal)', textShadow: '0 0 24px rgba(113,222,205,0.3)' }}>with the reasons kept.</span>
        </h1>
        <p style={{ fontSize: '1.2rem', lineHeight: 1.6, color: 'var(--text)', maxWidth: '820px', marginBottom: '32px' }}>
          A volunteer coordinator in a neighbourhood food network receives a surplus offer and has to decide who can take it, and be able to say why.
          <strong> Merismos</strong> checks the offer against the network’s own registers (food safety, capacity, equity and premises rules) and proposes a split with a reason on every line, including what nobody can take.
          A person approves the exact plan: approval records the decision. Merismos sends no message or notification and dispatches no vehicle.
        </p>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'center' }}>
          <a
            href={launchHref}
            onClick={handleNav('/dashboard', onLaunchCockpit)}
            className="button"
            data-testid="landing-launch-cockpit"
            style={{ fontSize: '1.05rem', padding: '14px 30px', background: 'var(--teal)', color: '#0c2527', textDecoration: 'none', fontWeight: 700, borderRadius: '10px', boxShadow: '0 4px 16px rgba(113, 222, 205, 0.3)' }}
          >
            Try the sample offer →
          </a>
          <a
            href="#/journeys"
            onClick={handleNav('/journeys')}
            className="button secondary"
            style={{ fontSize: '1.05rem', padding: '14px 24px', textDecoration: 'none', borderRadius: '10px' }}
          >
            How it works
          </a>
          <a
            href="#/architecture"
            onClick={handleNav('/architecture')}
            className="button secondary"
            style={{ fontSize: '1.05rem', padding: '14px 24px', textDecoration: 'none', borderRadius: '10px' }}
          >
            Architecture
          </a>
          <a
            href="#/impact"
            onClick={handleNav('/impact')}
            className="button secondary"
            style={{ fontSize: '1.05rem', padding: '14px 24px', textDecoration: 'none', borderRadius: '10px' }}
          >
            Impact &amp; limits
          </a>
        </div>

        <p className="small-note" style={{ marginTop: '24px', color: 'var(--secondary)' }}>
          Runs in your browser against an isolated sandbox session. No login, no install. Synthetic organisations and donations; nothing is published.
        </p>
      </section>

      {/* Three cards: the organisations, the cold chain, the record */}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', marginBottom: '36px' }}>
        <div className="panel padded" style={{ margin: 0, background: 'rgba(20, 26, 46, 0.85)', border: '1px solid var(--border)', borderRadius: '14px', backdropFilter: 'blur(10px)' }}>
          <span className="eyebrow">THE NETWORK</span>
          <strong style={{ display: 'block', fontSize: '2.4rem', margin: '8px 0', color: 'var(--teal)' }}>Five organisations</strong>
          <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', margin: 0 }}>
            Omonoia Soup Kitchen, Kypseli Food Pantry, Anemos Community Library, Second Chance School and Elpida Night Shelter. All synthetic.
            They differ in cold storage, whether they have a van, whether they serve the same day, and premises rules (alcohol-free, nut-free, no pork). The split has to respect each of those.
          </p>
        </div>
        <div className="panel padded" style={{ margin: 0, background: 'rgba(20, 26, 46, 0.85)', border: '1px solid var(--border)', borderRadius: '14px', backdropFilter: 'blur(10px)' }}>
          <span className="eyebrow">COLD CHAIN</span>
          <strong style={{ display: 'block', fontSize: '2.4rem', margin: '8px 0', color: 'var(--amber)' }}>Refused in full</strong>
          <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', margin: 0 }}>
            A broken cold chain is refused in full, and the refusal says why. Food-safety refusals are final: they are never reduced to a smaller quantity, and the model cannot clear them.
          </p>
        </div>
        <div className="panel padded" style={{ margin: 0, background: 'rgba(20, 26, 46, 0.85)', border: '1px solid var(--border)', borderRadius: '14px', backdropFilter: 'blur(10px)' }}>
          <span className="eyebrow">THE RECORD</span>
          <strong style={{ display: 'block', fontSize: '2.4rem', margin: '8px 0', color: 'var(--text)' }}>Append-only</strong>
          <p style={{ color: 'var(--secondary)', fontSize: '0.95rem', margin: 0 }}>
            Every ledger entry carries a body digest and a link to its parent. Corrections are new records that name what they replaced; the superseded record stays served with a notice. A digest binds bytes, not truth.
          </p>
        </div>
      </section>

      {/* How It Works: 3 Steps */}
      <section className="panel padded" style={{ marginBottom: '36px', background: 'rgba(20, 26, 46, 0.85)', borderRadius: '14px' }}>
        <div className="section-heading" style={{ marginBottom: '24px' }}>
          <div>
            <p className="eyebrow">HOW MERISMOS WORKS</p>
            <h2 style={{ fontSize: '1.6rem' }}>From an offer to a recorded collection in three steps</h2>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '24px' }}>
          <div style={{ borderTop: '2px solid var(--teal)', paddingTop: '16px' }}>
            <span style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--teal)' }}>01</span>
            <h3 style={{ margin: '8px 0', fontSize: '1.15rem' }}>Intake</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.6 }}>
              The offer is typed in: title, donor, quantity and unit, category (ambient, chilled or frozen), collection date, use-by, hours unrefrigerated, allergens and a note.
              Personal data (phone numbers, IBANs, card numbers, national IDs, named households) and instruction-like text are refused at the door, and the refusal names the field.
            </p>
          </div>
          <div style={{ borderTop: '2px solid var(--amber)', paddingTop: '16px' }}>
            <span style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--amber)' }}>02</span>
            <h3 style={{ margin: '8px 0', fontSize: '1.15rem' }}>The checks</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.6 }}>
              Four specialists (food safety, capacity, equity, premises) run as Strands agents and read the network’s registers through bounded read-only tools. A guard cancels any tool call outside the allowed corpus.
              A bounded solver then proposes the split: storage is a veto, transport is a cap, the network’s 40% ceiling is its own policy, and the remainder is stated.
            </p>
          </div>
          <div style={{ borderTop: '2px solid var(--text)', paddingTop: '16px' }}>
            <span style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--text)' }}>03</span>
            <h3 style={{ margin: '8px 0', fontSize: '1.15rem' }}>Human approval and record</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.92rem', lineHeight: 1.6 }}>
              A person approves the exact plan: consent to the exact record digest and address. A claim, an agreed collection time and an explicit “collection confirmed” are three separate recorded facts.
              No message is sent by Merismos.
            </p>
          </div>
        </div>
      </section>

      {/* Sample scenario, from the session data only */}
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
            <span className="eyebrow" style={{ color: 'var(--teal)' }}>SAMPLE OFFER</span>
            <h3 style={{ fontSize: '1.4rem', margin: '6px 0 10px' }}>
              {sampleOffer ? `${sampleOffer.title} (${sampleOffer.quantity} ${sampleOffer.unit})` : 'Sample offer not loaded'}
            </h3>
            <p style={{ color: 'var(--secondary)', margin: 0, maxWidth: '720px', fontSize: '0.95rem' }}>
              Donor: <strong>{sampleOffer?.donor || 'not loaded'}</strong> · Category: <strong>{sampleOffer?.category || 'not loaded'}</strong> · Collection date: <strong>{sampleOffer?.collection_date || 'date not provided'}</strong> · Use by: <strong>{sampleOffer?.use_by || 'date not provided'}</strong>.
              The split has to respect each organisation’s same-day service, cold storage, transport and premises rules, and every line carries a reason.
            </p>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '14px' }}>
              {sameDay && <span style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#163239', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #315853' }}>Same-day rule applies</span>}
              <span style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#163239', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #315853' }}>A reason on every line</span>
              <span style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#163239', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #315853' }}>Strands agent loop</span>
              <span style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#163239', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #315853' }}>Sandbox · scripted planner</span>
            </div>
          </div>
          <a
            href={routeLink('/workspace', { offer: sampleOffer?.id })}
            onClick={handleNav('/workspace')}
            className="button"
            style={{ padding: '12px 24px', whiteSpace: 'nowrap' }}
          >
            Open in the workspace →
          </a>
        </div>
      </section>

      {/* Footer Info */}
      <div style={{ marginTop: '36px', paddingTop: '20px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', fontSize: '0.85rem', color: 'var(--secondary)' }}>
        <span>Merismos (μερισμός): apportionment of one thing among several.</span>
        <div style={{ display: 'flex', gap: '20px' }}>
          <a href="#/impact" onClick={handleNav('/impact')} style={{ color: 'var(--secondary)' }}>Impact &amp; limits</a>
          <a href="#/architecture" onClick={handleNav('/architecture')} style={{ color: 'var(--secondary)' }}>Architecture</a>
          <a href="#/records" onClick={handleNav('/records')} style={{ color: 'var(--secondary)' }}>Records</a>
        </div>
      </div>
    </div>
  );
}
