import { useState } from 'react';
import { routeLink } from './routes';

interface ArchitectureNode {
  id: string;
  name: string;
  category: 'Edge & Delivery' | 'API & Routing' | 'Serverless Compute' | 'Agentic AI' | 'Storage & Audit';
  awsService: string;
  description: string;
  securityControls: string;
  costProfile: string;
  resilienceMechanism: string;
}

const NODES: ArchitectureNode[] = [
  {
    id: 'cloudfront',
    name: 'Amazon CloudFront Edge',
    category: 'Edge & Delivery',
    awsService: 'Amazon CloudFront',
    description: 'Serves the React single-page application globally with sub-second latency, TLS termination, and DDoS protection via AWS Shield Standard.',
    securityControls: 'Origin Access Control (OAC), HTTPS-only redirect, strict Content-Security-Policy headers.',
    costProfile: 'Negligible (Free Tier covers up to 1 TB outbound transfer and 10M requests).',
    resilienceMechanism: 'Multi-edge point of presence caching with automatic failover.',
  },
  {
    id: 'apigateway',
    name: 'HTTP API Gateway',
    category: 'API & Routing',
    awsService: 'Amazon API Gateway v2',
    description: 'Low-latency RESTful entry point routing incoming requests to specialized AWS Lambda functions with CORS preflight handling.',
    securityControls: 'IAM execution roles, throttle limits (100 req/sec burst), request validation.',
    costProfile: '$1.00 per million requests (70% cheaper than REST API Gateway).',
    resilienceMechanism: 'Regionally managed endpoint with automated horizontal scaling.',
  },
  {
    id: 'lambda',
    name: 'Modular Lambda Micro-Fleet',
    category: 'Serverless Compute',
    awsService: 'AWS Lambda (Python 3.13)',
    description: 'Stateless execution environment running the intake validator, multi-agent solver, human approval gate, and S3 publisher.',
    securityControls: 'Least-privilege IAM roles scoped to table ARNs, read-only root filesystem, ephemeral /tmp encryption.',
    costProfile: 'Pay-per-millisecond compute (ARM64 Graviton architecture reduces execution costs by 20%).',
    resilienceMechanism: 'Automatic retries with dead-letter queue routing for asynchronous dispatches.',
  },
  {
    id: 'strands',
    name: 'AWS Strands Multi-Agent Fleet',
    category: 'Agentic AI',
    awsService: 'AWS Strands SDK + Amazon Bedrock',
    description: 'Coordinates 5 distinct agentic evaluators representing beneficiary organisations, balancing cold-chain rules, travel distance, and fairness quotas.',
    securityControls: 'Guardrails for Amazon Bedrock, deterministic constraint enforcement filters, zero training on prompt inputs.',
    costProfile: 'Invoked only during active offer arbitration (~1,500 tokens per allocation scenario).',
    resilienceMechanism: 'Deterministic fallback heuristics if Bedrock experiences throttling or network timeouts.',
  },
  {
    id: 'dynamodb',
    name: 'Operational Single-Table Store',
    category: 'Storage & Audit',
    awsService: 'Amazon DynamoDB',
    description: 'Single-table design tracking active offers, recipient capacity limits, session tokens, and pickup task workflows.',
    securityControls: 'KMS encryption at rest, point-in-time recovery (PITR), condition expressions preventing duplicate claims.',
    costProfile: 'On-demand capacity mode (pay only for exact read/write request units consumed).',
    resilienceMechanism: 'Multi-AZ synchronous replication with sub-10ms latency.',
  },
  {
    id: 's3',
    name: 'Tamper-Evident Proof Bucket',
    category: 'Storage & Audit',
    awsService: 'Amazon S3',
    description: 'Immutable, publicly readable markdown archive holding cryptographic custody records for every completed food allocation.',
    securityControls: 'Public read-only bucket policy, S3 Object Lock for non-repudiation, SHA256 integrity verification.',
    costProfile: '$0.023 per GB/month for standard storage; sub-cent monthly cost.',
    resilienceMechanism: '11 nines (99.999999999%) of data durability across multiple availability zones.',
  },
];

export function ArchitectureView() {
  const [activeNodeId, setActiveNodeId] = useState('strands');
  const activeNode = NODES.find(n => n.id === activeNodeId) || NODES[0];

  return (
    <div className="architecture-view" style={{ maxWidth: '1280px', margin: '0 auto', padding: '16px 0 48px' }}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">WELL-ARCHITECTED SERVERLESS AGENTS</p>
          <h1>AWS Topology & Infrastructure</h1>
          <p>How Merismos leverages Amazon Bedrock, AWS Strands, Lambda, and S3 for mission-critical civic resilience.</p>
        </div>
        <a className="button" href={routeLink('/dashboard')}>
          Back to Cockpit →
        </a>
      </div>

      {/* Visual Topology Diagram */}
      <section className="panel padded" style={{ marginBottom: '28px', background: 'var(--panel)', border: '1px solid var(--border)' }}>
        <p className="eyebrow" style={{ textAlign: 'center', marginBottom: '16px' }}>INTERACTIVE SYSTEM TOPOLOGY (CLICK ANY LAYER TO INSPECT)</p>
        
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '14px' }}>
          {NODES.map(node => {
            const isSelected = node.id === activeNodeId;
            return (
              <button
                key={node.id}
                onClick={() => setActiveNodeId(node.id)}
                className="panel"
                style={{
                  margin: 0,
                  padding: '16px 12px',
                  textAlign: 'center',
                  cursor: 'pointer',
                  border: isSelected ? '2px solid var(--teal)' : '1px solid var(--border)',
                  background: isSelected ? 'var(--raised)' : 'var(--bg)',
                  transition: 'all 0.2s ease',
                }}
              >
                <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--secondary)', display: 'block', marginBottom: '6px' }}>
                  {node.category}
                </span>
                <strong style={{ display: 'block', fontSize: '0.95rem', color: isSelected ? 'var(--teal)' : 'var(--text)', lineHeight: 1.3 }}>
                  {node.name}
                </strong>
                <span className="badge" style={{ marginTop: '8px', fontSize: '0.7rem' }}>
                  {node.awsService}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      {/* Node Deep Dive Inspector */}
      <section className="panel padded" aria-labelledby="node-inspector-title">
        <div className="section-heading" style={{ borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '20px' }}>
          <div>
            <span className="eyebrow">{activeNode.category.toUpperCase()} · ARCHITECTURE DEEP DIVE</span>
            <h2 id="node-inspector-title" style={{ fontSize: '1.5rem', marginTop: '4px' }}>{activeNode.name} ({activeNode.awsService})</h2>
            <p style={{ color: 'var(--secondary)', margin: '4px 0 0', fontSize: '0.95rem' }}>{activeNode.description}</p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
          <div style={{ background: 'var(--bg)', padding: '18px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ color: 'var(--teal)' }}>SECURITY & PERMISSIONS</span>
            <h3 style={{ fontSize: '1rem', margin: '6px 0 10px' }}>Least-Privilege Isolation</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>
              {activeNode.securityControls}
            </p>
          </div>

          <div style={{ background: 'var(--bg)', padding: '18px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ color: 'var(--amber)' }}>COST OPTIMIZATION</span>
            <h3 style={{ fontSize: '1rem', margin: '6px 0 10px' }}>Pay-Per-Execution Economics</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>
              {activeNode.costProfile}
            </p>
          </div>

          <div style={{ background: 'var(--bg)', padding: '18px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ color: '#60a5fa' }}>RELIABILITY & FAULT TOLERANCE</span>
            <h3 style={{ fontSize: '1rem', margin: '6px 0 10px' }}>High-Availability Posture</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>
              {activeNode.resilienceMechanism}
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
