import React, { useState } from 'react';

interface TelemetryEvent {
  id: string;
  time: string;
  source: string;
  action: string;
  status: 'verified' | 'negotiating' | 'sealed';
  hash: string;
}

export function DashboardCharts() {
  const [activeDay, setActiveDay] = useState<number | null>(4); // default to Fri
  const [simulating, setSimulating] = useState(false);
  const [telemetryEvents, setTelemetryEvents] = useState<TelemetryEvent[]>([
    {
      id: 'evt-109',
      time: '14:28:12',
      source: 'Supermarket Sklavenitis (Fokionos)',
      action: 'Donation logged: 240kg bread & produce',
      status: 'sealed',
      hash: 's3://merismos-ledger/proof-9014.json [sha256:4f8e...]',
    },
    {
      id: 'evt-108',
      time: '14:25:03',
      source: 'Strands Multi-Agent Engine',
      action: 'Arbitrated: 5-shelter quotas balanced (Gini: 0.08)',
      status: 'verified',
      hash: 'strands:agent-arb:pass',
    },
    {
      id: 'evt-107',
      time: '14:24:45',
      source: 'Cold-Chain Guard',
      action: 'Thermal compliance verified (ambient pantry certified)',
      status: 'verified',
      hash: 'thermal:safe-ambient',
    },
    {
      id: 'evt-106',
      time: '13:50:22',
      source: 'Bakery Veneti (Patision)',
      action: 'Donation logged: 45kg day-end pastries',
      status: 'sealed',
      hash: 's3://merismos-ledger/proof-9013.json [sha256:bc31...]',
    },
  ]);

  const days = [
    { day: 'Mon', kg: 85, co2: 212 },
    { day: 'Tue', kg: 140, co2: 350 },
    { day: 'Wed', kg: 110, co2: 275 },
    { day: 'Thu', kg: 195, co2: 487 },
    { day: 'Fri', kg: 240, co2: 600 },
    { day: 'Sat', kg: 160, co2: 400 },
    { day: 'Sun', kg: 70, co2: 175 },
  ];
  const maxKg = 260;

  const shelters = [
    { name: 'St. Panteleimon Soup Kitchen', allocated: 280, capacity: 350, pct: 80, tag: 'High-volume hot meals' },
    { name: 'Kypseli Homeless Shelter', allocated: 175, capacity: 200, pct: 87.5, tag: 'Emergency overnight' },
    { name: 'Refugee Solidarity Center', allocated: 135, capacity: 150, pct: 90, tag: 'Family support' },
    { name: 'Elderly Care Network', allocated: 95, capacity: 120, pct: 79.2, tag: 'Direct home delivery' },
    { name: 'Youth Community Hub', allocated: 70, capacity: 80, pct: 87.5, tag: 'After-school pantry' },
  ];

  const runSimulation = () => {
    if (simulating) return;
    setSimulating(true);
    const newId = `evt-${Date.now().toString().slice(-4)}`;
    const now = new Date().toTimeString().split(' ')[0];

    setTimeout(() => {
      setTelemetryEvents(prev => [
        {
          id: newId,
          time: now,
          source: 'Supermarket AB Vassilopoulos',
          action: 'Ingested 120kg chilled dairy · Multi-agent split sealed to S3',
          status: 'sealed',
          hash: `s3://merismos-ledger/proof-${newId}.json [sha256:${Math.random().toString(16).slice(2, 8)}...]`,
        },
        ...prev.slice(0, 4),
      ]);
      setSimulating(false);
    }, 1000);
  };

  return (
    <div className="dashboard-charts-section" style={{ margin: '24px 0 28px' }}>
      {/* Top Visual Stats Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px', marginBottom: '24px' }}>
        
        {/* CHART 1: 7-Day Surplus Diversion SVG Bar Chart */}
        <div className="panel padded" style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: '14px', position: 'relative' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
            <div>
              <span className="eyebrow" style={{ color: 'var(--teal)', fontSize: '0.78rem', fontWeight: 700, letterSpacing: '0.08em' }}>
                7-DAY SURPLUS RECOVERY (KG)
              </span>
              <h3 style={{ margin: '4px 0 0', fontSize: '1.25rem', fontWeight: 700 }}>
                1,000 kg Diverted
              </h3>
            </div>
            <span style={{ fontSize: '0.8rem', padding: '4px 10px', background: '#163239', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #315853' }}>
              +22% vs. last week
            </span>
          </div>

          {/* SVG Bar Chart */}
          <div style={{ height: '180px', width: '100%', position: 'relative' }}>
            <svg viewBox="0 0 350 180" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
              <defs>
                <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#71decd" stopOpacity="0.9" />
                  <stop offset="100%" stopColor="#153e42" stopOpacity="0.4" />
                </linearGradient>
                <linearGradient id="activeBarGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#f3ce86" stopOpacity="1" />
                  <stop offset="100%" stopColor="#80653b" stopOpacity="0.5" />
                </linearGradient>
              </defs>

              {/* Grid Lines */}
              <line x1="20" y1="20" x2="330" y2="20" stroke="#232a45" strokeDasharray="3,3" strokeWidth="1" />
              <line x1="20" y1="70" x2="330" y2="70" stroke="#232a45" strokeDasharray="3,3" strokeWidth="1" />
              <line x1="20" y1="120" x2="330" y2="120" stroke="#232a45" strokeDasharray="3,3" strokeWidth="1" />
              <line x1="20" y1="150" x2="330" y2="150" stroke="#354260" strokeWidth="1" />

              {/* Bars */}
              {days.map((item, idx) => {
                const barWidth = 28;
                const x = 30 + idx * 44;
                const barHeight = (item.kg / maxKg) * 125;
                const y = 150 - barHeight;
                const isActive = activeDay === idx;

                return (
                  <g key={item.day} onClick={() => setActiveDay(idx)} style={{ cursor: 'pointer' }}>
                    <rect
                      x={x}
                      y={y}
                      width={barWidth}
                      height={barHeight}
                      rx="4"
                      fill={isActive ? 'url(#activeBarGrad)' : 'url(#barGrad)'}
                      stroke={isActive ? 'var(--amber)' : '#3c746e'}
                      strokeWidth={isActive ? '1.5' : '1'}
                      style={{ transition: 'all 0.2s ease' }}
                    />
                    <text
                      x={x + barWidth / 2}
                      y="168"
                      textAnchor="middle"
                      fill={isActive ? 'var(--amber)' : 'var(--secondary)'}
                      fontSize="11"
                      fontWeight={isActive ? '700' : '500'}
                    >
                      {item.day}
                    </text>
                    <text
                      x={x + barWidth / 2}
                      y={y - 6}
                      textAnchor="middle"
                      fill={isActive ? '#ffffff' : 'var(--teal)'}
                      fontSize="10"
                      fontWeight="600"
                    >
                      {item.kg}k
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>

          {activeDay !== null && (
            <div style={{ marginTop: '12px', padding: '10px 14px', background: 'var(--bg)', borderRadius: '8px', border: '1px solid var(--border)', fontSize: '0.85rem', display: 'flex', justifyContent: 'space-between' }}>
              <span>Selected: <strong>{days[activeDay].day}</strong></span>
              <span>Rescued: <strong style={{ color: 'var(--teal)' }}>{days[activeDay].kg} kg</strong></span>
              <span>CO₂e Avoided: <strong style={{ color: 'var(--amber)' }}>{days[activeDay].co2} kg</strong></span>
            </div>
          )}
        </div>

        {/* CHART 2: 5-Shelter Quota Equity Breakdown */}
        <div className="panel padded" style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px' }}>
            <div>
              <span className="eyebrow" style={{ color: 'var(--teal)', fontSize: '0.78rem', fontWeight: 700, letterSpacing: '0.08em' }}>
                RECIPIENT QUOTA FAIR-SHARE (GINI: 0.08)
              </span>
              <h3 style={{ margin: '4px 0 0', fontSize: '1.25rem', fontWeight: 700 }}>
                Kypseli Network Equity
              </h3>
            </div>
            <span style={{ fontSize: '0.8rem', padding: '4px 10px', background: '#173c3c', color: 'var(--teal)', borderRadius: '999px', border: '1px solid #3c746e' }}>
              Fairness: 99.2%
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '11px' }}>
            {shelters.map(s => (
              <div key={s.name} style={{ fontSize: '0.82rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text)' }}>{s.name}</span>
                  <span style={{ color: 'var(--secondary)' }}>
                    <strong>{s.allocated}</strong> / {s.capacity} kg ({s.pct}%)
                  </span>
                </div>
                <div style={{ width: '100%', height: '8px', background: '#202b42', borderRadius: '4px', overflow: 'hidden' }}>
                  <div
                    style={{
                      width: `${s.pct}%`,
                      height: '100%',
                      background: s.pct >= 90 ? 'var(--amber)' : 'var(--teal)',
                      borderRadius: '4px',
                      transition: 'width 0.4s ease-out',
                    }}
                  />
                </div>
              </div>
            ))}
          </div>

          <p style={{ margin: '14px 0 0', fontSize: '0.78rem', color: 'var(--secondary)', lineHeight: 1.5 }}>
            Strands Agents prevent starvation of smaller community kitchens by factoring historical allocations into every arbitration turn.
          </p>
        </div>

      </div>

      {/* REAL-TIME NETWORK TELEMETRY & EVENT STREAM */}
      <div className="panel padded" style={{ background: 'linear-gradient(135deg, #13192f 0%, #162436 100%)', border: '1px solid #2a3c5a', borderRadius: '14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span
              style={{
                display: 'inline-block',
                width: '10px',
                height: '10px',
                borderRadius: '50%',
                background: '#4ade80',
                boxShadow: '0 0 10px #4ade80',
                animation: 'pulse 1.8s infinite',
              }}
            />
            <div>
              <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700, color: '#ffffff' }}>
                Live Network Telemetry & Event Stream
              </h4>
              <p style={{ margin: 0, fontSize: '0.78rem', color: 'var(--secondary)' }}>
                Real-time Strands agent negotiations, cold-chain checks, and tamper-evident S3 ledger commits.
              </p>
            </div>
          </div>

          <button
            onClick={runSimulation}
            disabled={simulating}
            className="button"
            style={{
              padding: '8px 18px',
              fontSize: '0.85rem',
              background: simulating ? '#233045' : 'var(--teal)',
              color: simulating ? 'var(--secondary)' : '#0c2527',
              cursor: simulating ? 'not-allowed' : 'pointer',
              fontWeight: 700,
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            {simulating ? 'Arbitrating Agents…' : '▶ Simulate Live Ingest Cycle'}
          </button>
        </div>

        {/* Telemetry Stream Items */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {telemetryEvents.map(evt => (
            <div
              key={evt.id}
              style={{
                display: 'grid',
                gridTemplateColumns: '75px 1.4fr 2fr 1.6fr',
                gap: '12px',
                padding: '9px 12px',
                background: 'rgba(11, 15, 30, 0.65)',
                border: '1px solid #232d4b',
                borderRadius: '8px',
                fontSize: '0.8rem',
                alignItems: 'center',
              }}
            >
              <span style={{ fontFamily: 'ui-monospace, monospace', color: 'var(--secondary)' }}>{evt.time}</span>
              <strong style={{ color: 'var(--text)' }}>{evt.source}</strong>
              <span style={{ color: '#d0d7e6' }}>{evt.action}</span>
              <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: '0.75rem', color: 'var(--teal)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {evt.hash}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
