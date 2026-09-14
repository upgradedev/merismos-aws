# Merismos

Merismos helps a volunteer food coordinator split donations across community organisations: rules and agents check every share before the coordinator approves the exact plan.

[Open the coordinator workspace](https://d2qnkmlhs7y5fp.cloudfront.net/), with no account or installation for the synthetic sandbox.

[CI](https://github.com/upgradedev/merismos-aws/actions/workflows/ci.yml) · [Frontend verification](https://github.com/upgradedev/merismos-aws/actions/workflows/frontend-ci.yml) · [MIT licence](LICENSE)

## Try one short flow

No typing is needed, and the sandbox publishes nothing.

1. On the **Dashboard** choose **Start with this offer →** (**Continue my work →** on a return visit).
2. Choose **Work out the split**, review who receives a share and why, tick the consent box and choose **Approve in sandbox**.
3. Choose **Open collection tasks →** and **Claim this share**, tick the confirmation box and choose **Confirm collection**.

To try an invented donation, choose **+ Add offer → Try success**, edit the fields, choose **Add to sandbox**, then
**Work out the split**. A recorded allocation is not a collected donation. Also in the sandbox:

- **Try refusal** fills in a broken cold chain; after **Add to sandbox** and **Work out the split** it is refused in full and never offered for approval.
- **Try correction** fills in a phone-shaped note: intake refuses it on **Add to sandbox**, keeps the fields and accepts a corrected note.
- In **Evidence bundle and recovery**, **Copy evidence bundle** copies the decision, sources, run, revision, provider, mode, history and limits.
- **Import a donor CSV instead** (under **+ Add offer**) files only the rows you select. **Rehearse a collection disruption** proposes a new plan after one recipient's capacity drops. **Pickup manifest · copy or download** gives a plain-text handoff that sends no message.
- **About this demo**, in the page footer, shows the provider, the snapshot time and the automated test reports.

## Contents

- [Try one short flow](#try-one-short-flow)
- [What is real and what is demonstrated](#what-is-real-and-what-is-demonstrated)
- [Architecture](#architecture)
- [Cost and sustainability](#cost-and-sustainability)
- [Run it locally](#run-it-locally)
- [Documentation](#documentation)
- [Validation and release](#validation-and-release)
- [Pre-existing components and licences](#pre-existing-components-and-licences)

## What is real and what is demonstrated

The five community organisations are synthetic, and the donors, donations and example collection confirmations
are invented; none of it is evidence of food rescued. Merismos is a browser workspace: a coordinator can copy its
summary into an existing channel, and there is no automatic chat delivery, email, telephony or payment.

The public sandbox runs the real **Strands Agents SDK** agent loop and tool guard with `scripted-planner/1.0.0`, a
scripted test model, so the sandbox makes no Bedrock call and no model network call. A sandbox session stops working
after 24 hours, but its stored item is not deleted automatically.

**Live records are publicly read-only.** Live mode is the private path in which an authenticated network
coordinator's approval publishes a public record. A live change needs an API Gateway Lambda authorizer that
identifies a network coordinator with `merismos:coordinate`. None is deployed on the public API, so every public
live change is refused with 403. A typed name, body identity or client-supplied header is not authentication.

Strands is load-bearing: removing the SDK stops the agent journey, and removing its `BeforeToolCallEvent` guard lets
a denied tool call through in the negative-control test. A separate deterministic gate checks each draft, so not
every refusal comes from the Strands guard. Live runs use Amazon Bedrock with `eu.anthropic.claude-opus-5`, and a
public request cannot start one; a configured model is not evidence that a run called it. An optional critic, a
second Bedrock call with no tools that reviews the prose about an allocation, is off by default and is not a
separate Lambda. Merismos does not run on AgentCore. The 40% ceiling, under which no organisation receives more than
40% of one offer, is this network's policy, not a universal or certified definition of fairness.

Not measured: human active time, time saved, food rescued, beneficiary impact and adoption. Not run: human
acceptance testing, the authenticated publication and recovery drill (ME18), real-device Safari testing and a timed
first-use test. The first published
[offer-4471 record](https://merismos-records-e6ac6047.s3.eu-west-1.amazonaws.com/records/offer-4471.md)
contains a known contradictory allocation, preserved as historical evidence, not repaired automatically and not
presented as a correct plan. [Evidence and honest limits](docs/evidence.md) has the evidence levels, retained
artifact IDs and acceptance receipts.

## Architecture

A browser reaches Amazon CloudFront, which serves the React app from a private S3 bucket and passes API requests,
uncached, to an Amazon API Gateway HTTP API. The API invokes the reader, one of four AWS Lambda functions built from
one package; the reader runs each sandbox run inside the request and keeps sessions in the DynamoDB thread table.
Live runs happen in the runner, which calls Amazon Bedrock; with no authorizer deployed, the only trigger in this
repository is `deploy.yml`, dispatched by hand. Of the four functions, only the writer publishes records to the
public S3 records bucket, after exact approval.

```mermaid
flowchart TB
    accTitle: Merismos overview, what runs where
    accDescr: A coordinator's browser reaches Amazon CloudFront, which serves the app from an S3 bucket and forwards API paths to API Gateway, which has no authorizer. The reader Lambda answers the API, runs sandbox runs with a scripted model and keeps sessions in DynamoDB. The runner Lambda runs live agents with Amazon Bedrock when a GitHub Actions proof run starts it, and records run events in DynamoDB. The writer Lambda spends an approval in DynamoDB and creates a publicly readable record in S3. Dotted arrows are the live coordinator path, which the public API refuses.

    Visitor("Coordinator's browser"):::browser
    Cdn[/"Amazon CloudFront"/]:::edge
    Site[("S3 site bucket")]:::store
    Api[/"API Gateway, no authorizer"/]:::edge
    Reader["Reader Lambda: API and sandbox runs"]:::agent
    Runner["Runner Lambda: live runs"]:::agent
    Writer["Writer Lambda: records"]:::agent
    Tables[("DynamoDB tables")]:::store
    Records[("S3 records, public read")]:::store
    Bedrock[["Amazon Bedrock"]]:::model
    Actions[/"GitHub Actions"\]:::cicd

    Visitor -->|"HTTPS"| Cdn
    Cdn -->|"app files"| Site
    Cdn -->|"API paths"| Api
    Api --> Reader
    Reader -->|"sessions"| Tables
    Reader -.->|"live run"| Runner
    Reader -.->|"live approval"| Writer
    Actions -->|"proof runs"| Runner
    Runner -->|"model calls"| Bedrock
    Runner -->|"run events"| Tables
    Writer -->|"spends approval"| Tables
    Writer -->|"creates record"| Records

    classDef browser fill:#116ad1,stroke:#0c4c96,stroke-width:2px,color:#ffffff
    classDef edge fill:#16787e,stroke:#10565b,stroke-width:2px,color:#ffffff
    classDef agent fill:#b64c05,stroke:#833704,stroke-width:2px,color:#ffffff
    classDef store fill:#576f89,stroke:#3f5063,stroke-width:2px,color:#ffffff
    classDef model fill:#be308a,stroke:#892363,stroke-width:2px,color:#ffffff
    classDef cicd fill:#7f6a03,stroke:#5b4c02,stroke-width:2px,color:#ffffff
```

In the diagram, the blue rounded box is the coordinator's browser, teal parallelograms are AWS entry points, orange
rectangles are Lambda functions, slate cylinders are data stores (the DynamoDB thread and approvals tables and two
S3 buckets), the magenta double-sided box is Amazon Bedrock and the olive trapezoid is GitHub Actions. Dotted
arrows are the live coordinator path, which the public API refuses. To stay readable at page width, the diagram
leaves out the S3 corpus that the reader, runner and writer read, the EventBridge Scheduler wake that only appends
an escalation and the release job that publishes the app; [Infrastructure](docs/infrastructure.md) draws them.

Three fleet IAM roles separate the reader, evaluator and writer; the runner runs under the reader role, and
EventBridge Scheduler has its own role. The evaluator Lambda, not in the diagram, only answers identity probes; the
product's draft gate runs inside the reader-role functions. Among the three fleet roles only the writer holds
`s3:PutObject` on the records bucket; the GitHub deploy role, created outside Terraform, can also write to the
Merismos buckets. The Secrets Manager value is a boundary canary that the publish path never reads: the writer may
read it, and the reader and evaluator are denied. Read on in the
[governed flow of one offer](docs/architecture.md#governed-flow-of-one-offer), the
[trust boundaries](docs/architecture.md#trust-boundaries) and the [infrastructure inventory](docs/infrastructure.md).

## Cost and sustainability

**The live proof in one deploy apply costs a median of $1.62.** This was measured read-only over the five deploy
applies between 2026-09-09 and 2026-09-13 that called the model. Each proof invokes the background runner twice: for
offer-4471, which the model answers, and for the refused offer-4477. How the cost splits between those two
invocations is not measured. At the AWS Pricing API's eu-west-1 on-demand prices the five proofs cost $1.44 to $1.78
each, with a median of $1.62, and Bedrock is about 99.6% of it. Taken column by column, the medians were 43 Bedrock
calls to `eu.anthropic.claude-opus-5`, 170,499 input and 23,712 output tokens, and 365.6 Lambda GB-seconds; no single
proof had all four. Not measured: cache tokens, cold-start initialisation time, DynamoDB, S3, CloudFront, Scheduler,
logs, data transfer and the actual invoice. How CloudTrail attributed the calls is in
[Cost and latency](docs/cost-and-latency.md#measured-cost-of-the-live-proof).

**The public sandbox never calls a model.** Every sandbox run uses the scripted planner inside the reader Lambda
(`bedrock.scripted_analyst()` in `src/merismos/api.py`). A visitor therefore costs API Gateway requests, Lambda
time, on-demand DynamoDB reads and writes, and CloudFront and S3 requests. The functions are not attached to a
virtual private cloud (VPC), so there is no hourly NAT gateway or VPC endpoint charge. In the product, Bedrock runs
only in live runs, which start only through an IAM-authorised invocation of the runner.

Terraform defaults limit how far a problem can spread
([what bounds a problem](docs/cost-and-latency.md#what-bounds-a-problem)). The API is throttled to 10 requests per
second with a burst of 20, and at most 5 readers and 4 background runners run at once. The reader's asynchronous
invokes are never retried automatically (the runner keeps Lambda's default retries), and the two alarms notify
nobody. The hackathon rules require the entry to stay reachable until judging ends on 2026-10-08 17:00 PT;
`still-up.yml` fetches the API Gateway URL and one published record anonymously every Monday and Thursday at 09:00
UTC. [Cost and latency](docs/cost-and-latency.md) also has the sandbox latency sample and how `deploy.yml` tears the
deployment down.

## Run it locally

No AWS account and no credentials, and once installed, no network. That last claim is itself a test: the offline
suite intercepts every socket and fails the run on any address but loopback. You need Python 3.10 or later (CI uses
3.13) and the repository root as your working directory. This is a src-layout package, so nothing is importable
until it is installed; install time depends on your network and was not measured.

```bash
pip install -e ".[dev]"
```

```bash
python -m merismos.demo
```

Three offers run to an outcome. Under the `MERISMOS` banner, the first lines name the ledger, the model and the
scheduler this run actually used, so a fallback to a stub would say so:

```text
  ledger      memory
  model       scripted-planner/1.0.0
  scheduler   none

  OFFLINE PATH. No AWS account is in use and nothing here opens a socket.
```

```bash
python scripts/the_swap_test.py
```

The guard is a hook on the agent loop, not a sentence in the prompt. The swap test replaces Strands with a module
that fails when used, and prints `SWAP TEST PASSED.` only if the demo journey then fails at the expected assertion.

```bash
python -m pytest -q
```

The full offline suite: unit, integration, regression and end-to-end tests, with the 85% coverage floor CI enforces.
The coordinator UI needs Node 22 (CI pins 22.18.0). Start the offline HTTP harness that CI uses in one terminal, and
the UI in another:

```bash
python tests/http_server.py
```

```bash
cd frontend && npm ci && npm run dev
```

Open the address Vite prints. `/api` is proxied to the harness on `127.0.0.1:8765`, which keeps sandbox state in
SQLite and never supplies live coordinator authorisation. In `frontend/`, `npm test` runs the unit suite. For the
browser journeys, first stop the harness: Playwright starts its own on `127.0.0.1:8765`, plus a preview server of
the built app. Then run `npm run build && npx playwright install --with-deps chromium webkit && npm run test:e2e`
for the desktop, mobile and `mobile-webkit` journeys. `mobile-webkit` is Playwright's WebKit engine with the iPhone
13 preset, not real-device Safari. CI runs these commands, except `npm run dev`, and runs the suite as `pytest -q`.

## Documentation

- [Architecture](docs/architecture.md): how one offer moves from intake to a recorded collection, and where each trust boundary sits.
- [Infrastructure](docs/infrastructure.md): which AWS resources exist, what each IAM role may do, and what is not deployed.
- [Evidence and honest limits](docs/evidence.md): what each evidence level proves, and what stays NOT_RUN.
- [Model evaluation](docs/model-evaluation.md): the preregistered interpretation evaluation, prepared but not run.
- [Cost and latency](docs/cost-and-latency.md): how the figures were measured, what bounds a problem, and how the deployment comes down.
- [Release and validation](docs/release-and-validation.md): what each workflow checks, and how a change reaches AWS.
- [All documents](docs/README.md): every page in `docs/`, the dated records and where to start in the code.

## Validation and release

- **CI** runs on every pull request: a full-history secret scan, Ruff (the Python linter), the offline suite with
  the 85% coverage floor and no AWS credentials, the guard and SDK-removal checks, and Terraform format and
  validation. The offline suite also checks every relative link, repository link and heading anchor in the README
  and `docs/`.
- **Frontend verification** runs on every pull request: dependency audits, the React build, unit tests with coverage
  floors, and Playwright journeys against the real Python HTTP API.
- **Docs verification** runs when the README or `docs/` change: it lints the Markdown and renders every Mermaid
  diagram with Mermaid 11.17.2, the version GitHub served when it was pinned on 2026-09-14.
- **A push to `main`** verifies again, checks the deployed backend against the runtime source, publishes the
  frontend and runs the live Playwright testbook against AWS. The backend deploys only when someone dispatches
  `deploy.yml` by hand, and it defaults to a dry run.

[Current AWS acceptance](https://d2qnkmlhs7y5fp.cloudfront.net/acceptance.html) reports the served release separately
from the dated checkpoints in the [acceptance testbook](frontend/UAT.testbook.html). The acceptance receipt takes the
answering backend's commit from `GET /api/version` observations of CI-packaged metadata before and after the
journeys, and refuses to build if the two differ. Human acceptance stays **NOT_RUN** until a person signs off. Step
by step: [Release and validation](docs/release-and-validation.md).

## Pre-existing components and licences

The existing disclosure states that the application code was written during the submission period. The author
brought prior agent-fleet experience and an existing personal visual design direction; the Merismos components were
implemented for this application. No prior product source code, dependencies, customer data, tenant configuration
or customer assets were reused. The filing is explicitly synthetic.

Strands Agents SDK, boto3 and botocore retain their Apache 2.0 licences. Development tools and frontend dependencies
retain their own licences. Dependencies are not vendored or modified. Merismos is MIT licensed; see
[LICENSE](LICENSE). Existing video pipeline schema/provider settings are production-tool contracts, not claims about
the application's runtime.
