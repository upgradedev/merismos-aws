# Merismos: Enterprise Amazon Bedrock AgentCore Alignment Architecture

This specification details how Merismos' autonomous multi-agent institutional fleet maps to the **Amazon Bedrock AgentCore** architecture and enterprise runtime primitives.

> **Read this first. Merismos does not run on AgentCore.** Sections 1 to 4 are a mapping: they say
> which AgentCore primitive each part of this fleet corresponds to, and they are written to be
> checked against the code. **Section 5 is what is actually deployed**, which is Lambda, the Strands
> Agents SDK and Bedrock `Converse`. Nothing in this document should be read as a claim that the
> deployed system uses AgentCore, and the one section that used to read that way is corrected and
> says so.

---

## 1. Executive Summary

Merismos deploys a decentralized fleet of institutional agents for civil society organizations and food pantry networks that cannot afford full-time administrative staff to manage surplus donation logistics.

The system ensures that **no AI agent ever publishes an allocation unilaterally**. Instead, deterministic specialists, combinatorial constraint solvers, and an adversarial critic operate under strict IAM separation, presenting a single cryptographic approval card for human sign-off.

```
                 An offer arrives
        POST /run  ·  or an EventBridge Scheduler wake
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  merismos-reader   ·   AWS Lambda   ·   its own IAM role            │
│                                                                     │
│   router  ->  food-safety   capacity   equity   premises            │
│                                                                     │
│   each specialist runs a Strands Agent:                             │
│     model  ->  tool  ->  reasoning  ->  answer                      │
│     model:  eu.anthropic.claude-opus-5  (Bedrock Converse)          │
│                                                                     │
│   Guard  ·  Strands BeforeToolCallEvent  ·  sets cancel_tool        │
│   Bounded reads: scope, traversal, size, 6 per specialist           │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ draft
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  merismos.solver   ·   deterministic, no model                      │
│    40% ceiling · capacity limits · conservation · feasibility proof │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  merismos-evaluator  ·  AWS Lambda  ·  second IAM role              │
│    7 deterministic checks. Holds no S3, no Bedrock, no read tool    │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ sanitised envelope only
                              ▼
              eu.amazon.nova-pro-v1:0  ·  independent critic
              called with no toolConfig. Advisory, cannot subtract
                              │
                              ▼
        approval card  ·  sha256 over network, key and exact bytes
                              │
                       a person approves
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  merismos-writer  ·  AWS Lambda  ·  third IAM role                  │
│    recomputes the digest · spends the nonce · s3:PutObject          │
└─────────────────────────────┬───────────────────────────────────────┘
                              ▼
        a public S3 object anyone can read with no account

  Provenance: DynamoDB, append only by interface, parent_id chained
  Deferrals:  EventBridge Scheduler one-shot at(...), self deleting
```

---

## 2. Bedrock AgentCore Primitive Mapping

| Merismos Component | Bedrock AgentCore Equivalent | Implementation & Role |
| :--- | :--- | :--- |
| **`merismos.fleet.run_chore`** | **Supervisor Agent (Orchestrator)** | Coordinates the specialized evaluation passes, executes deterministic gates, and mints approval cards. |
| **`merismos.fleet.SPECIALISTS`** | **Collaborating Domain Agents** | Four specialized agents evaluating Food Safety (temperature, best-before dates), Storage Capacity (refrigeration volume), Equity (two-in-a-row rota), and Premises Constraints (allergens, alcohol, pork). |
| **`merismos.solver`** | **Deterministic Action Group** | Operations Research constraint solver enforcing the $\le 40\%$ single-pantry quota and proving non-over-allocation mathematically. |
| **`merismos.bedrock.BedrockCritic`** | **Bedrock Guardrail & Evaluator** | A second model family, called through `Converse` with **no `toolConfig`**, so it is not an agent and has no dispatcher to ask. It sees the sanitiser's output and never the draft, and its result can only be added to what a person reads. |
| **`merismos.approval`** | **Bedrock Return-of-Control (ROC)** | sha256 over network, key and the exact bytes, in DynamoDB. The approval is valid for **15 minutes**, not 24 hours; the DynamoDB TTL sits a day past expiry so an expired approval is still there to refuse with. The nonce is spent by a conditional write, so one approval authorises one write. |
| **`merismos.guard.decide`** | **AgentCore IAM Tool Boundary** | In-process authorization control hook blocking unauthorized tool calls before invocation. |

---

## 3. Combinatorial Solver & Invariant Enforcement

To eliminate reliance on LLM hallucinations for resource allocation, Merismos incorporates a deterministic Operations Research solver (`merismos.solver`):

1. **Hard Quota Ceiling:** $\forall p \in \text{Pantries}, \text{Allocated}_p \le 0.40 \times \text{TotalOffered}$.
2. **Storage Capacity Constraints:** $\forall p, \text{Allocated}_p \le \text{Capacity}_p$.
3. **Conservation Invariant:** $\sum_p \text{Allocated}_p \le \text{TotalOffered}$.
4. **Allergen / Premises Exclusion:** If an organization's premises policy bans a declared ingredient (e.g. alcohol, nuts, non-halal/kosher), $\text{Allocated}_p = 0$.

---

## 4. Bedrock Multi-Agent Security & Least Privilege

```
IAM, as deployed. Role names are lower case and hyphenated.

  merismos-reader      s3:GetObject on the corpus, bedrock:InvokeModel/Converse,
                       dynamodb PutItem/Query/GetItem, scheduler:CreateSchedule,
                       lambda:InvokeFunction on the other two.
                       NO s3:PutObject anywhere. It cannot publish.

  merismos-evaluator   dynamodb:PutItem on the thread, and nothing else.
                       NO S3, NO Bedrock, NO read tool of any kind.

  merismos-writer      s3:PutObject scoped to records/* and probes/* on the
                       records bucket, and to offers/* on the corpus bucket,
                       dynamodb GetItem/UpdateItem on approvals,
                       secretsmanager:GetSecretValue on the boundary canary.
                       NO reach into orgs/ or registers/, which are the register
                       of members and the policy it is judged against.
```

**Why the writer holds the corpus prefix and the reader does not.** A coordinator
can file their own offer through a form on the public site, so an offer is now
something a stranger can create rather than something a fixture supplies. That is
a write, and every write in this system happens under the one identity that is
allowed to write. The reader takes the form, validates it so the person is told
immediately, and then asks the writer over the `lambda:InvokeFunction` grant it
already held for publishing. It gains no new AWS authority at all, which is the
property that keeps the three-identity argument standing.

The writer does not trust what it is handed. It receives **the form**, not an
offer the reader assembled, and rebuilds the offer with the same intake rules,
in the same way it recomputes the digest rather than trusting a publish payload.
The S3 key is constructed from an id matched against `offer-` plus digits, so
this route cannot be aimed at a published record. And the put carries
`IfNoneMatch: *`, so S3 itself refuses to turn an intake into an overwrite of an
offer that has already been read or decided about.

**`s3:PutObject` is the publish authority.** The Secrets Manager value is a canary the publish path
never reads; it exists so a refusal is observable from all three identities. `/identity` attempts
both and reports what AWS said to each. An earlier version of this file, and of the README, called
the canary "the publish credential", which overstated it.

The evaluator deliberately holds **zero read tools**. Any attempts by an untrusted donation manifest to prompt-inject the Critic are neutralized because the Critic cannot access corpus files, environment credentials, or network sockets.

---

## 5. What is actually deployed, which is not the same as section 2

Sections 1 to 4 are a **mapping**: this component, that AgentCore equivalent. This section is the
deployment, and the two must not be read as one thing. Merismos does **not** run on AgentCore today.

| | What is built and deployed | What section 2 maps it to |
|---|---|---|
| **Runtime** | Four AWS Lambda functions, one package, three IAM roles. The fourth is the reader's own role in a separate concurrency pool, so a nine minute chore cannot make the site unanswerable. The agent loop is the **Strands Agents SDK**, not a managed agent runtime | AgentCore Runtime |
| **Models** | `eu.anthropic.claude-opus-5` for the specialists, through Bedrock `Converse`. `eu.amazon.nova-pro-v1:0` as an independent critic, called with no `toolConfig` | AgentCore model configuration |
| **Tool boundary** | `merismos.guard.decide`, enforced in the Strands `BeforeToolCallEvent` hook by setting `cancel_tool` | AgentCore IAM tool boundary |
| **Trigger** | `POST /run` on the reader, plus **EventBridge Scheduler one-shot `at(...)` schedules** for a parked decision. There is no S3 `ObjectCreated` trigger | EventBridge |
| **Approval state** | DynamoDB, TTL enabled, nonce spent by a conditional write. **This row is built as described** | AgentCore Memory |
| **Audit ledger** | DynamoDB, append only **by interface**: no update or delete method exists in the code. No object level immutability feature is enabled on any bucket, so this is weaker than a storage guarantee and the README says so | AgentCore Memory |

**Why AgentCore is not used.** The rules name it as strengthening Technical Implementation, so this
is a deliberate cost rather than an oversight. The control this entry argues for is a refusal inside
the tool dispatcher, and that is a Strands hook: `BeforeToolCallEvent` sets `cancel_tool` and the
tool is never invoked. Moving to a managed runtime would mean re-establishing that control on
somebody else's dispatcher, and the proof that it has teeth, a CI job that removes the hook and
watches the same model reach the tool, is the single most load-bearing test in the repository.

This section previously named a managed agent runtime, two older Claude models and a bucket
immutability feature as the deployment. None of the four is deployed. Corrected 2026-09-04, before
the repository was made public, by a check that compares every capability word in this file against
the code.

The old wording is described rather than reproduced, deliberately. A check over source text cannot
tell a claim from a quotation of one, so a correction that repeats the phrase it corrects trips the
check written to catch the original. That is a rule this workspace learned three times in one day
and it applies to this paragraph.
