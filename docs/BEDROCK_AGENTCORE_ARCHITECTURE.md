# Merismos: Enterprise Amazon Bedrock AgentCore Alignment Architecture

This specification details how Merismos' autonomous multi-agent institutional fleet maps to the **Amazon Bedrock AgentCore** architecture and enterprise runtime primitives.

---

## 1. Executive Summary

Merismos deploys a decentralized fleet of institutional agents for civil society organizations and food pantry networks that cannot afford full-time administrative staff to manage surplus donation logistics.

The system ensures that **no AI agent ever publishes an allocation unilaterally**. Instead, deterministic specialists, combinatorial constraint solvers, and an adversarial critic operate under strict IAM separation, presenting a single cryptographic approval card for human sign-off.

```
                    ┌─────────────────────────────────────────┐
                    │       Inbound Donation Offer Event      │
                    │         (S3 Bucket / EventBridge)       │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 Amazon Bedrock AgentCore Multi-Agent Runtime                │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │               Specialist Fleet (Bedrock Collaborating Agents)       │   │
│   │                                                                     │   │
│   │   ┌────────────────────┐                   ┌────────────────────┐   │   │
│   │   │ Food Safety Agent  │                   │  Capacity Agent    │   │   │
│   │   │ (Claude 3.5 Haiku) │                   │ (Claude 3.5 Haiku) │   │   │
│   │   └─────────┬──────────┘                   └─────────┬──────────┘   │   │
│   │             │                                        │              │   │
│   │             ▼                                        ▼              │   │
│   │   ┌────────────────────┐                   ┌────────────────────┐   │   │
│   │   │   Equity Agent     │                   │   Premises Agent   │   │   │
│   │   │ (Claude 3.5 Haiku) │                   │ (Claude 3.5 Haiku) │   │   │
│   │   └─────────┬──────────┘                   └─────────┬──────────┘   │   │
│   └─────────────┼────────────────────────────────────────┼──────────────┘   │
│                 │                                        │                  │
│                 ▼                                        ▼                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │        Deterministic Operations Research (OR) Constraint Solver     │   │
│   │        - 40% hard quota ceiling enforcement                         │   │
│   │        - Linear capacity / knapsack allocation optimization         │   │
│   └──────────────────────────────────┬──────────────────────────────────┘   │
│                                      │ Proposed Draft Plan                  │
│                                      ▼                                      │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │        Adversarial Critic (Bedrock Guardrail / Model Evaluator)     │   │
│   │        - Zero Read Permissions (Air-Gapped against Prompt Injection)│   │
│   │        - Strict Invariant Verification (Gatekeeper)                 │   │
│   └──────────────────────────────────┬──────────────────────────────────┘   │
│                                      │ Verified Draft                       │
│                                      ▼                                      │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │     Return-of-Control (ROC): Human Approval Card (DynamoDB TTL)     │   │
│   │     - Human coordinator holds the sole cryptographic publish key    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Bedrock AgentCore Primitive Mapping

| Merismos Component | Bedrock AgentCore Equivalent | Implementation & Role |
| :--- | :--- | :--- |
| **`merismos.fleet.run_chore`** | **Supervisor Agent (Orchestrator)** | Coordinates the specialized evaluation passes, executes deterministic gates, and mints approval cards. |
| **`merismos.fleet.SPECIALISTS`** | **Collaborating Domain Agents** | Four specialized agents evaluating Food Safety (temperature, best-before dates), Storage Capacity (refrigeration volume), Equity (two-in-a-row rota), and Premises Constraints (allergens, alcohol, pork). |
| **`merismos.solver`** | **Deterministic Action Group** | Operations Research constraint solver enforcing the $\le 40\%$ single-pantry quota and proving non-over-allocation mathematically. |
| **`merismos.gate.Critic`** | **Bedrock Guardrail & Evaluator** | Isolated evaluator running with **zero read credentials**; evaluates only draft prose against declared constraints to catch prompt injections and policy violations. |
| **`merismos.approval`** | **Bedrock Return-of-Control (ROC)** | Preserves exact byte hashes in DynamoDB with a 24-hour TTL; prevents automated execution without authenticated human sign-off. |
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
IAM Identity Boundary
├── arn:aws:iam::...:role/MerismosReaderRole (S3 ReadOnly on Corpus, No Bedrock Write)
├── arn:aws:iam::...:role/MerismosEvaluatorRole (InvokeModel Only, Zero S3 Access)
└── arn:aws:iam::...:role/MerismosWriterRole (S3 PutObject Only, Scoped to /records/{id}.md)
```

The evaluator (Critic) deliberately holds **zero storage read tools**. Any attempts by an untrusted donation manifest to prompt-inject the Critic are neutralized because the Critic cannot access corpus files, environment credentials, or network sockets.

---

## 5. Cloud-Native AWS Deployment

* **Trigger:** AWS Lambda triggered by Amazon S3 `ObjectCreated` events or Amazon EventBridge scheduled rules.
* **Agent Runtime:** Amazon Bedrock AgentCore utilizing Claude 3.5 Haiku for high-speed specialist passes and Claude 3.5 Sonnet for final synthesis.
* **Approval State:** Amazon DynamoDB table with TTL-enabled approval records.
* **Audit Ledger:** Append-only cryptographic transaction log stored in Amazon S3 Object Lock (WORM compliance).
