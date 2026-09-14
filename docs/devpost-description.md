# Merismos

Merismos helps a volunteer food coordinator plan how one donation is split across community organisations, review that split and keep its reasons beside the collection handoff.

[Open Merismos](https://d2qnkmlhs7y5fp.cloudfront.net/). No account or installation is needed for
the synthetic sandbox. On the **Dashboard** choose **Start with this offer →** (on a return visit
the button reads **Continue my work →**). On **Decide** choose **Work out the split**, tick "I have
reviewed this exact allocation and record address, and approve this plan." and choose **Approve in
sandbox**. On **Pickups** choose **Claim this share**, tick "This collection actually happened in
the simulation." and choose **Confirm collection**. To try your own invented donation, choose
**+ Add offer → Try success**, edit the fields, choose **Add to sandbox**, then **Work out the
split**.

Up to four specialists (food safety, capacity, equity, premises) apply deterministic rules first
and, where those rules do not already refuse, run as agents on the Strands Agents SDK, reading the
network's files through read-only tools. A Merismos guard on the SDK's `BeforeToolCallEvent` hook
cancels any tool call the role may not make. A deterministic solver proposes the split; a person
approves the exact plan and separately confirms each collection. The public sandbox uses a scripted
model and makes no Bedrock call. Live runs use Amazon Bedrock with `eu.anthropic.claude-opus-5`, and
no public request can start one. Measured: the live proof in one deploy apply costs a median of
$1.62 over five applies at eu-west-1 on-demand prices (Bedrock tokens and Lambda only), and a
scripted sandbox run request took a median of 426 ms over 10 HTTP samples from one workstation.
Not done: human acceptance testing, real-device Safari testing and a timed first-use test. Unlike a
group chat, a shared spreadsheet or a general chat assistant, Merismos checks each share against
storage, premises rules and the network's 40% ceiling before a person agrees to it.

## The problem and the product

A coordinator allocating a donation across community organisations needs to know who can accept
it, why another organisation was excluded and what remains unallocated. Merismos keeps those
decisions with the pickup commitments instead of making the coordinator reconstruct them later.
This is a synthetic demonstration with five invented organisations, not an adoption study.

Try refusal demonstrates a broken cold chain. Try correction demonstrates a refused phone-shaped
note that remains editable. Each example only fills the form; choosing **Add to sandbox** submits
it to the real HTTP API. The dashboard shows the next donation, allocation totals and collection
states, not estimated savings.

The Dashboard names the next offer and gives it one primary button. In the sandbox, a banner reads
"Sandbox · synthetic data · nothing is published". The approval, intake and collection buttons say
why they are disabled, for example "Available once you tick the box above." Frontend CI runs the
browser journeys at desktop and mobile viewport sizes.

## How it works

Intake refuses personal data (phone numbers, email and street addresses, bank account and card
numbers, national identifiers, named households) and instruction-like text. The refusal says what
kind of personal data it found and asks for a description of the food, not the people.

Up to four specialists check each offer: food safety, capacity, equity and premises. Each applies
deterministic rules first. Where those rules do not already refuse, the specialist runs as an agent
and reads the network's files through read-only tools, with a read budget of 6 per specialist. The
model's answer can add caution but cannot clear a refusal, so a broken cold chain is refused in full.

A bounded deterministic solver then proposes the split. Storage is a veto and transport is a cap.
No organisation receives more than 40% of one offer; that is this network's own policy, not a
universal fairness rule. What nobody can take is shown as a remainder. A separate deterministic
gate checks the draft record for personal data before it can be approved.

## What the sponsor supplies

The **Strands Agents SDK** runs each specialist's agent loop and dispatches its tool calls.
Merismos registers its own guard on the SDK's `BeforeToolCallEvent` hook. The guard cancels any
tool call the deployed role may not make, before the tool runs. In CI, removing the guard lets a
negative-control publish call reach the tool. Replacing Strands with a module that fails when used
makes the offline demo journey and the coordinator screens fail at a named assertion. The public
sandbox run builds a real Strands agent with the scripted model, and the API returns an error when
that agent does not run.

The public sandbox uses a scripted test model, `scripted-planner/1.0.0`, with no model network call.
It is not Bedrock inference. Live runs use Amazon Bedrock with `eu.anthropic.claude-opus-5`. A
public request cannot start one; the deploy proof starts them with IAM-authorised invocations of
the internal runner. Each deploy apply invokes the runner for offer-4471, which should reach a
plan, and for offer-4477, which should be refused, and the apply fails unless the offer-4471 run
records a specialist answer that came from the model.

The live proof in one deploy apply costs a median of $1.62. This was measured read-only over the
five deploy applies between 2026-09-09 and 2026-09-13 that called the model, at the AWS Pricing
API's eu-west-1 on-demand prices, counting Bedrock tokens and Lambda only. The five proofs cost
$1.44 to $1.78 each, and Bedrock is about 99.6% of it. How the cost splits between the two runner
invocations is not measured. Taken column by column, the medians were 43 Bedrock calls, 170,499
input and 23,712 output tokens and 365.6 Lambda GB-seconds; no single proof had all four.
CloudTrail attributes the Opus 5 calls in those proof windows to the `merismos-reader` role, which
the runner runs under.

An optional critic, a second tool-less Bedrock read, is supported but off by default:
`critic_model_id` defaults to empty and the deploy workflow does not set it. Merismos does not run
on Amazon Bedrock AgentCore.

## AWS services and architecture

- Amazon CloudFront and a private, versioned Amazon S3 bucket serve the site.
- An Amazon API Gateway HTTP API fronts the reader, one of four AWS Lambda functions built from one
  package. The runner, evaluator and writer have no API Gateway route.
- Amazon DynamoDB holds the ledger, sandbox workspaces and approvals.
- Amazon S3 holds the network's corpus and the published records.
- Three AWS IAM roles separate the reader, evaluator and writer; the runner runs under the reader
  role. An AWS Secrets Manager value is a boundary canary that the publish path never reads.
- Amazon EventBridge Scheduler, with an Amazon SQS dead-letter queue, wakes deferred decisions.
- Amazon CloudWatch keeps logs and holds two alarms.
- In the product, Amazon Bedrock serves live runs only.

An architecture diagram is in the Architecture section of `README.md` in the submitted repository.

## Human control, evidence and limits

The agents and the solver only propose. A person decides. They tick "I have reviewed this exact
allocation and record address, and approve this plan." and press **Approve in sandbox**. A person
also claims each share for an organisational role, may set a collection time, and must tick that
the collection actually happened before **Confirm collection**. A refused offer is never offered for
approval, and a recorded allocation is never counted as a collection.

Live history is publicly read-only. Every live change needs a coordinator authorizer. Live
publication also needs a current passing plan and explicit exact consent. No coordinator authorizer
is deployed on the public API, so every public live change is refused with 403, and the public site
supplies no coordinator sign-in. Typed names and client identity headers cannot authorize
publication. A draft the gate refused is marked "Gate refused" on its offer and never becomes
publishable.

Publishing a record needs s3:PutObject on the records bucket, and of the three fleet roles only the
writer holds it. The reader, and the runner under the reader role, cannot make that write, and the
evaluator has no corpus or model access. Each deploy apply checks that AWS refuses the reader that
write. The coordinator's identity is recorded as a hash, and sandbox session handles are hashed
before they become storage keys.

The writer uses conditional creation; a correction takes a new address and leaves original bytes
unchanged. Explicit authenticated recovery checks one saved attempt and can complete its receipt
without publishing again. A timeout is an unknown outcome, not a retry instruction.

Terraform defaults bound cost: an API throttle of 10 requests per second with a burst of 20,
reserved concurrency of 5 for the reader and 4 for the runner, and no automatic retries of reader
asynchronous invokes. Neither CloudWatch alarm has an alarm action, so an alarm notifies nobody.

A sandbox session is one item in the DynamoDB thread table. Its handle stops working after 24
hours, but the table has no TTL, so the item is not deleted automatically. Approval rows carry a
DynamoDB TTL one day after their 15-minute expiry. Published live records are publicly readable in
a versioned S3 bucket with no expiry rule. Logs are kept 14 days, and the API access log records
caller IP addresses.

The human-readable evidence bundle includes public source references, decision reasons, run and
workspace revision, provider/mode, record history, handoff and recovery limits. Hashes bind bytes,
not source truth or delivery. A coordinator may copy the bundle; Merismos sends no chat, email or
phone message. A saved allocation is not proof of collection.

No measured time saved, human active time, food rescued, compliance or beneficiary impact is
claimed. The only latency figure is a sandbox HTTP sample taken on 2026-09-13 against deployed
commit `cb97c9e`, an earlier release than the one live now: one workstation, 10 samples 15 s apart,
0 failures, and a median of 426 ms for a scripted sandbox run (max 2,628 ms). It is not a load
test, browser render time or Lambda cold-start time. Live mode was not measured. The dated
`docs/live-run-2026-09-02.md` in the submitted repository records one earlier live specialist read
at its own checkpoint. The contradictory historical offer-4471 record remains disclosed in the
Evidence and honest limits section of `README.md`; it is not silently repaired.

Current code, CI and live deployment are separate evidence levels. Core CI runs on pushes to main
and feature branches and on pull requests: a full-history secret scan, Ruff, the offline test suite
with an 85% coverage floor and no AWS credentials, the guard and SDK-removal checks, and Terraform
validation. Frontend CI builds the React app and runs Playwright journeys against the real Python
HTTP API at desktop and mobile viewport sizes in Chromium, and three of those journeys in
Playwright WebKit with an iPhone 13 preset, which is not real-device Safari. A push to main
publishes the frontend and reruns the desktop and mobile Chromium journeys against the deployed
site in the scripted sandbox. The backend deploys only by manual dispatch. Human acceptance
testing, real-device Safari testing and a timed first-use test have not been done. New testbook
cases and human signoff stay NOT_RUN until actually tested.

## How this differs from what a network uses today

A group chat or a shared spreadsheet can record who takes what. Neither checks a share against an
organisation's storage, premises rules or the network's 40% ceiling before it is agreed. Neither
keeps the reason an organisation was excluded beside the pickup. A general chat assistant can
propose a split, but nothing checks it against the register, and it leaves no exact plan for a
person to approve. Merismos puts those checks in code and in a tool guard, and leaves the decision
with a person. These comparisons describe the general kind of tool, not a hands-on evaluation of
any product.

## Disclosure

The code was implemented for Merismos during the submission period, as the existing disclosure
records. The author brought prior fleet experience and a personal visual design direction; no prior
product code, customer data, configuration or assets were reused. Merismos uses the Strands Agents
SDK, boto3 and botocore unmodified, under their Apache 2.0 licences. It builds on the SDK with
role-bounded read-only tools, the guard hook, the deterministic draft gate, the allocation solver
and exact-plan approval. Merismos is MIT licensed. Settings in the separate video production
pipeline describe that tool, not the application's runtime. `README.md` in the submitted
repository has the exact validation, retained evidence IDs and deployment limitations. This file is
a draft, not proof that a submission form or video was published.
