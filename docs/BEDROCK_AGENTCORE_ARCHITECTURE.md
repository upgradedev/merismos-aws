# Merismos — AWS execution and trust boundaries

For a community-food coordinator: [open Merismos](https://d2qnkmlhs7y5fp.cloudfront.net/),
choose Add an offer → Try success, edit the donation and review the exact plan.
The public sandbox uses real HTTP persistence and Strands with a scripted model, no model network
call or public publication. Live records are publicly read-only.

## Runtime, not a platform claim

Merismos runs on AWS Lambda, DynamoDB, S3 and CloudFront. It does **not** run on AgentCore.
Strands Agents SDK is load-bearing in specialist tool dispatch and the BeforeToolCallEvent guard.
The deterministic gate is a separate control. The internal runner retains configured
`eu.anthropic.claude-opus-5`; a particular model call needs run evidence. Optional tool-less
critic support does not establish a deployed or invoked critic Lambda.

| Boundary | Authority and limit |
| --- | --- |
| Public reader / runner role | Corpus reads, bounded agent tools, ledger state and approved internal invocations; no S3 PutObject. Public live changes require a trusted coordinator authorizer. |
| Evaluator role | Draft-only gate, thread PutItem/GetItem for persisted custody; no corpus reads or model authority. |
| Writer role | Approval GetItem/conditional UpdateItem; exact fresh passing draft; record conditional create. Corpus reads/list only offers/, orgs/, registers/; corpus writes only offers/. Record reads only for exact-attempt recovery. |
| Coordinator consent | Current workspace revision, run, evidence, bytes and address. A typed approved_by name is not authentication. |
| Custody | Event + persisted head conditional transaction for new runs. Old events remain unchanged; a digest is not source truth. |

The nonce is spent before S3 and receipt append follows S3. Therefore transport failure can leave
an unknown outcome. GET only projects saved state. Explicit authenticated recovery checks one
reserved approval against actual object metadata and bytes, then appends a missing receipt without
a second publication. Missing or mismatched objects require investigation; no blind retry.

New receipts use the network partition, category and recipient organisations. Readers also retain
legacy category partitions. Fairness uses the last two distinct same-category donations, not
corrections, and preserves the existing 40% cap. History without those fields remains unknown.

Record URLs are stable. Conditional creation prevents application overwrite but is not WORM;
external administrative changes and delete markers remain limits. No historical row or object is
automatically repaired. The known contradictory record remains disclosed in the README.

## Deployment and evidence

The source IAM change needs a manual Terraform dry run and human plan review before authorized
apply, preserving resource identities and current Opus 5 configuration. CI Terraform validation is
not evidence of deployed-role behavior. The deploy proof uses genuine IAM internal worker
invocation for model execution; anonymous mutation probes assert 403 and public history stays
read-only. No new public authentication mechanism is simulated.

Evidence bundles show public sources, decisions, revision, run/provider/mode, failure/recovery and
handoff. Hashes do not prove food safety, delivery, compliance or savings. Time saved, human active
time and impact are unmeasured. See the README and existing testbook for exact CI/AWS evidence,
NOT_RUN gaps, retained historical disclosures and dependency licences.
