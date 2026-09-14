# Merismos

Maria, a fictional volunteer food coordinator, uses Merismos rules and Strands agents to check each share before
approving an exact allocation.

**Good Neighbor Agents · Human-approved food sharing, checked by Strands agents**

[Open the working AWS application](https://d2qnkmlhs7y5fp.cloudfront.net/). No account or installation is needed.
Choose **+ Add offer → Try success** to edit an invented donation, then **Add to sandbox** and **Work out the
split**. The public sandbox runs the real Strands loop with a fixed tool sequence and closing answer, but makes no
model network call. It publishes nothing, sends nothing automatically and leaves live records read-only.

## The problem, who it is for and why it matters

Volunteer coordinators in community food networks decide which organisations can safely accept each share of a
donation. They also need to explain exclusions, keep the remainder visible and know who will collect each share.
A chat or spreadsheet can record an answer, but it does not check storage, transport, premises and network
allocation rules before agreement. A split without those checks and reasons can be unsafe, impossible to collect
or hard for the network to review later.

Merismos keeps the checks, the allocation and the collection handoff together while leaving approval and
collection confirmation with a person.

## What it does

Merismos is an AWS-hosted browser workspace with a complete synthetic journey:

1. File or edit an invented surplus-food offer.
2. Refuse personal data, instruction-like text or a broken cold chain with a visible reason.
3. Ask eligible specialists to inspect the network registers and work out a policy-bounded split.
4. Review who receives each share, why another organisation cannot and what remains.
5. Approve the exact plan, then separately claim and confirm a simulated collection.
6. Copy the evidence bundle or pickup manifest for review. Merismos sends no message itself.

The public demo is the deployed application, not slides or a mock-up. It uses the React interface, public HTTP API,
AWS Lambda and DynamoDB session storage. The five organisations, every offer and every confirmation are invented.

## How we use Strands Agents

The **Strands Agents SDK** is load-bearing. Up to four specialists cover food safety, capacity, equity and premises.
Each specialist applies deterministic rules first. A specialist blocked by those rules never calls a model. Each
eligible specialist then runs as a Strands agent and reads the network corpus through role-bounded, read-only tools
with a six-read budget.

Merismos registers a guard on Strands' `BeforeToolCallEvent` hook. It cancels any tool call the role may not make
before the tool executes. Negative-control tests remove the guard and prove that the denied call reaches the tool.
A separate swap test replaces Strands with a module that fails when used and proves that the coordinator journey
then stops at a named assertion.

The public sandbox creates a real Strands agent with `scripted-planner/1.0.0`, a fixed tool sequence and closing
answer, without a model network call. Separately, frozen backend proof
[run 34894779949](https://github.com/upgradedev/merismos-aws/actions/runs/34894779949) configured and exercised
`eu.anthropic.claude-opus-5` through the private IAM-authorised Amazon Bedrock runner at backend
`4bf2238dda6e9663cbae65ea14e1951ce7ed9cea`. Public requests cannot start that live path.

## How it is built

Amazon CloudFront serves the React application from a private Amazon S3 bucket and forwards API traffic to Amazon
API Gateway and a reader Lambda. DynamoDB stores sandbox workspaces, decisions and approvals. A private runner
Lambda invokes Amazon Bedrock for live proof runs. Among the runtime fleet roles, only the writer role can create
public S3 records after exact approval.

Separate AWS IAM roles, Amazon EventBridge Scheduler with an Amazon SQS dead-letter queue, Amazon CloudWatch and
an AWS Secrets Manager boundary canary expose and enforce the trust boundaries. Terraform defines the
infrastructure. GitHub Actions validates and releases it.

## Human control, evidence and limits

The agents and solver propose. A person approves the exact allocation and record address. Approval does not count
as collection. A second explicit action claims a share, and another confirms that the simulated collection
happened.

The evidence bundle keeps logical source references from the current API snapshot, reasons, run identity,
workspace revision, provider, mode and record history together. A digest binds bytes, not source truth, food
safety or delivery. The deploy-time writer read-capability check in run 34894779949 was not a publication drill or
human signoff.

No public coordinator authorizer is deployed. Public live mutations return 403, and no typed name or client header
can confer authority. Messaging, email, payments and vehicle dispatch are not connected. No food-rescue, adoption,
time-saving, human active-time or beneficiary-impact claim is made. Human acceptance, authenticated publication
and recovery, real-device Safari and a timed first-use test remain not run.

## Try the complete journey

[Open Merismos](https://d2qnkmlhs7y5fp.cloudfront.net/), then:

**Dashboard → Start with this offer → Work out the split → review and consent → Approve in sandbox → Open
collection tasks → Claim this share → confirm → Confirm collection**

The refusal and correction paths are beside the successful sample. The source, architecture diagrams and evidence
are in the [public repository](https://github.com/upgradedev/merismos-aws).

## Built With

Strands Agents SDK, Amazon Bedrock, AWS Lambda, Amazon API Gateway, Amazon DynamoDB, Amazon S3, Amazon CloudFront,
Amazon EventBridge Scheduler, Amazon SQS, AWS IAM, AWS Secrets Manager, Amazon CloudWatch, Python, React, Terraform
and GitHub Actions.

## Disclosure

The application code was written for Merismos during the submission period. The author brought prior agent-fleet
experience and a personal visual direction, but no prior product code, customer data, tenant configuration or
customer assets. Strands Agents SDK, boto3 and botocore retain their Apache 2.0 licences. Merismos uses the MIT
licence. The submission video uses ElevenLabs narration; those provider settings belong to the production tool,
not the application runtime.

---

Everything above this divider is the **About the project** field. The remaining copy belongs in Devpost's separate
fields.

## Elevator pitch

Human-approved food sharing, checked by Strands agents.

## Built With tags

Enter these as separate tags, in this order:

`strands-agents`, `amazon-bedrock`, `aws-lambda`, `amazon-api-gateway`, `amazon-dynamodb`, `amazon-s3`,
`amazon-cloudfront`, `amazon-eventbridge-scheduler`, `amazon-sqs`, `aws-iam`, `aws-secrets-manager`,
`amazon-cloudwatch`, `python`, `react`, `typescript`, `tailwind-css`, `vite`, `terraform`

## Testing instructions

No account, installation or credentials are needed. The demo uses invented data and does not publish a record or
send a message.

1. Open <https://d2qnkmlhs7y5fp.cloudfront.net/> and keep **Workspace** set to **My sandbox**. For a clean run,
   open **About this demo → Start over in a new sandbox → Yes, start fresh**.
2. Select **+ Add offer → Try success**. Optionally change **What is being donated?**, then select **Add to
   sandbox**.
3. Select **Go to next decision ↓** if it appears, then **Work out the split**. Wait for **Approve this exact plan**
   and review the proposed shares, reasons and visible remainder.
4. Open **Read the exact record text**, tick **I have reviewed this exact allocation and record address, and approve
   this plan.**, then select **Approve in sandbox**.
5. Select **Open collection tasks →**, then **Claim this share**. Tick **This collection actually happened in the
   simulation.** and select **Confirm collection**. Expect **Simulation confirmed**.
6. Use **Decide** in the left navigation and expand **Evidence bundle and recovery** to inspect or copy the reasons,
   logical source references, run identity, revision and limits.

Optional safety check: choose **Dashboard → + Add offer → Try refusal → Add to sandbox → Work out the split**.
Expect **Safety refusal** and no approval control.

This exercises the deployed React and CloudFront app, API Gateway, Lambda, DynamoDB and the real Strands Agents SDK
loop with a fixed scripted planner. The public sandbox makes no Bedrock or model network call and publishes or sends
nothing.

## Project media captions

- `docs/assets/devpost-thumbnail.png`: The no-login synthetic Dashboard opens on one food offer and the complete
  allocation-to-collection journey.
- `docs/assets/overview.png`: Merismos on AWS: CloudFront serves the app, Lambda runs Strands, and the writer Lambda
  path publishes after exact approval.
- Final demo video: End-to-end product demo: edit an offer, review the checked split, approve the exact plan, then
  confirm collection separately.
- Acceptance evidence screen: Release-bound evidence identifies the deployed frontend and backend and records the
  automated desktop and mobile journeys.

The production video workflow also exports focused stills for the offer, proposed allocation, human approval,
architecture and evidence scenes. Use those only after the workflow has produced and verified them.
