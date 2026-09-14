import { useState } from 'react';
import { routeLink } from './routes';

interface ArchitectureNode {
  id: string;
  name: string;
  category: 'Edge & delivery' | 'API & identity' | 'Compute' | 'Agents' | 'State & records' | 'Deferrals';
  awsService: string;
  description: string;
  securityControls: string;
  costProfile: string;
  resilienceMechanism: string;
}

const NOT_MEASURED = 'Not measured per component. The live proof in one deploy apply cost a median of $1.62 in total, almost all of it Bedrock; see Cost and sustainability in the README.';

const NODES: ArchitectureNode[] = [
  {
    id: 'cloudfront',
    name: 'CloudFront + S3 SPA',
    category: 'Edge & delivery',
    awsService: 'Amazon CloudFront · Amazon S3',
    description: 'The React + Vite single-page application is served from an S3 bucket behind Amazon CloudFront. CI publishes it on push to main and writes the exact commit into release.json.',
    securityControls: 'The SPA holds no publishing authority. Live writes are decided on the API side by an authorizer grant that is not deployed on the public API; nothing the browser sends in a header or body can confer it.',
    costProfile: NOT_MEASURED,
    resilienceMechanism: 'The served build can be matched to a commit through release.json. No other mechanism is claimed for the frontend.',
  },
  {
    id: 'apigateway',
    name: 'HTTP API + function URLs',
    category: 'API & identity',
    awsService: 'Amazon API Gateway HTTP API',
    description: 'An API Gateway HTTP API (v2) with a catch-all route to the reader Lambda. A Lambda function URL for the reader and a private function URL also exist.',
    securityControls: 'Live mutations require a network-coordinator grant (merismos:coordinate, network-scoped) in the API Gateway authorizer context. No authorizer is deployed on the public API, so every public mutation is refused with 403; no header or body value can confer the grant. The sandbox needs no grant and cannot publish.',
    costProfile: NOT_MEASURED,
    resilienceMechanism: 'The stage throttles at 10 requests per second with a burst of 20, so an open endpoint cannot run up cost. The integration times out at 30 seconds, which is why a run is started in the background rather than awaited.',
  },
  {
    id: 'lambda',
    name: 'Four Lambdas, one package',
    category: 'Compute',
    awsService: 'AWS Lambda (Python 3.13)',
    description: 'Four functions (reader, evaluator, writer, runner) built from one package by for_each, with a shared dependency layer; the runner executes under the reader role. Reader: 1024 MB, 60 s. Runner: 1024 MB, 900 s. Evaluator and writer: 512 MB, 30 s.',
    securityControls: 'Three IAM role policies (reader, evaluator, writer). Only the writer holds s3:PutObject on the records bucket, which is what publishing a record needs.',
    costProfile: NOT_MEASURED,
    resilienceMechanism: 'Reserved concurrency in separate pools: at most 5 readers and 4 background runners at once, so a busy run queues instead of taking the site down. No automatic retries on the reader. CloudWatch alarms at 5 reader errors in 5 minutes and 500 reader invocations in an hour; they notify nobody, because no notification target is configured. Logs are kept 14 days.',
  },
  {
    id: 'identity',
    name: 'Identity separation',
    category: 'API & identity',
    awsService: 'AWS IAM · AWS Secrets Manager',
    description: 'Three IAM role policies: reader, evaluator, writer. Only the writer can publish a record.',
    securityControls: 'Publishing needs s3:PutObject on the records bucket, and of the three fleet roles only the writer holds it. The Secrets Manager value is a boundary canary that the publish path never reads: a never_the_publish_credential policy denies it to the reader and the evaluator, so each refusal can be observed. /identity?all=1 asks each identity what it can do and reports the answer.',
    costProfile: NOT_MEASURED,
    resilienceMechanism: 'None claimed. Separation is a control on who can write, not a failover mechanism.',
  },
  {
    id: 'dynamodb',
    name: 'DynamoDB: thread + approvals',
    category: 'State & records',
    awsService: 'Amazon DynamoDB',
    description: 'Two tables: thread, the append-only ledger, and approvals. Each thread entry carries a body digest (body_sha) and a parent link. Workspace sessions live in DynamoDB in AWS and in SQLite in the CI harness.',
    securityControls: 'Append-only by interface: entries are added, never edited in place. The custody summary reports what it cannot see.',
    costProfile: NOT_MEASURED,
    resilienceMechanism: 'Point-in-time recovery is enabled on both tables.',
  },
  {
    id: 's3',
    name: 'S3: corpus + records',
    category: 'State & records',
    awsService: 'Amazon S3',
    description: 'The corpus bucket holds the network registers: public access blocked, versioned. The records bucket holds published Markdown records: versioned, public read via bucket policy, so a published record has a stable public address.',
    securityControls: 'Corpus: public access blocked. Records: public read only, via bucket policy; only the writer identity can publish. Records carry SHA-256 digests, which bind bytes, not truth.',
    costProfile: NOT_MEASURED,
    resilienceMechanism: 'Both buckets are versioned. A correction is a new record at the next address that names what it replaced; the superseded record stays served with a notice.',
  },
  {
    id: 'scheduler',
    name: 'EventBridge Scheduler + SQS DLQ',
    category: 'Deferrals',
    awsService: 'Amazon EventBridge Scheduler · Amazon SQS',
    description: 'A block that turns on something changeable is parked with a reason and a one-shot schedule in a schedule group. A scheduler role fires the wake; an SQS dead-letter queue catches wakes that fail.',
    securityControls: 'Wakes are fired by a dedicated scheduler role.',
    costProfile: NOT_MEASURED,
    resilienceMechanism: 'Failed wakes land in the SQS dead-letter queue. There is no dead-letter queue for HTTP requests.',
  },
  {
    id: 'strands',
    name: 'Strands agents',
    category: 'Agents',
    awsService: 'Strands Agents SDK · Amazon Bedrock (live)',
    description: 'Four specialists (food safety, capacity, equity, premises) built with Agent and @tool from strands-agents>=1.53.0. Live mode uses BedrockModel; the model id is a Terraform variable and a separate critic model variable exists. The sandbox and CI use ScriptedPlanner, a Model subclass with scripted responses: a real agent loop, no Bedrock call.',
    securityControls: 'Tools are bounded and read-only with a budget of distinct paths. A BeforeToolCallEvent hook cancels any tool call outside the allowed corpus. A deterministic gate checks the draft record for personal data before it can be approved.',
    costProfile: 'About 99.6% of the $1.62 median cost of the live proof in one deploy apply, which runs offer-4471 and the refused offer-4477. Per-column medians over the five applies: 43 calls, 170,499 input tokens and 23,712 output tokens. No Bedrock call happens in the sandbox.',
    resilienceMechanism: 'The swap test proves the demo stops when the SDK is replaced. Food-safety refusals are final; the model cannot clear one.',
  },
];

export function ArchitectureView() {
  const [activeNodeId, setActiveNodeId] = useState('strands');
  const activeNode = NODES.find(n => n.id === activeNodeId) || NODES[0];

  return (
    <div className="architecture-view" style={{ maxWidth: '1280px', margin: '0 auto', padding: '16px 0 48px' }}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">WHAT ACTUALLY RUNS</p>
          <h1>AWS architecture</h1>
          <p>Each component below is deployed by infra/main.tf; nothing is listed that is not.</p>
        </div>
        <a className="button" href={routeLink('/dashboard')}>
          Back to the dashboard →
        </a>
      </div>

      {/* Component selector */}
      <section className="panel padded" style={{ marginBottom: '28px', background: 'var(--panel)', border: '1px solid var(--border)' }}>
        <p className="eyebrow" style={{ textAlign: 'center', marginBottom: '16px' }}>COMPONENTS (SELECT ONE TO INSPECT)</p>

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

      {/* Component detail */}
      <section className="panel padded" aria-labelledby="node-inspector-title">
        <div className="section-heading" style={{ borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '20px' }}>
          <div>
            <span className="eyebrow">{activeNode.category.toUpperCase()} · DETAIL</span>
            <h2 id="node-inspector-title" style={{ fontSize: '1.5rem', marginTop: '4px' }}>{activeNode.name} ({activeNode.awsService})</h2>
            <p style={{ color: 'var(--secondary)', margin: '4px 0 0', fontSize: '0.95rem' }}>{activeNode.description}</p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
          <div style={{ background: 'var(--bg)', padding: '18px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ color: 'var(--teal)' }}>IDENTITY &amp; ACCESS</span>
            <h3 style={{ fontSize: '1rem', margin: '6px 0 10px' }}>Who can do what</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>
              {activeNode.securityControls}
            </p>
          </div>

          <div style={{ background: 'var(--bg)', padding: '18px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ color: 'var(--amber)' }}>COST</span>
            <h3 style={{ fontSize: '1rem', margin: '6px 0 10px' }}>What it costs to run</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>
              {activeNode.costProfile}
            </p>
          </div>

          <div style={{ background: 'var(--bg)', padding: '18px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ color: '#60a5fa' }}>FAILURE HANDLING</span>
            <h3 style={{ fontSize: '1rem', margin: '6px 0 10px' }}>What is in place</h3>
            <p style={{ color: 'var(--secondary)', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>
              {activeNode.resilienceMechanism}
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
