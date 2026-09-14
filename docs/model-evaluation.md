# Model evaluation

An actual comparable model evaluation is **NOT_RUN**. No model-quality claim is made. The repository holds the parts of a future evaluation, prepared in source: a preregistered protocol, 14 synthetic cases with separately stored answers, a scoring script, a collector prepared to make 14 capped calls to `eu.anthropic.claude-opus-5` that runs only if the owner configures a grant with a reserved budget and dispatches it by hand, and a separately preregistered variant that asks the model to cite its sources. CI exercises these scripts with fake model responses only; none of them has been run against a model. The sections below record the protocol and its safeguards for review.

## Interpretation evaluation

This is source preparation, not measured model quality.

### Registration and scope

The [fixed protocol](../evaluation/interpretation-protocol.json),
[14 synthetic inputs](../evaluation/interpretation-inputs.json) and
[separate gold](../evaluation/interpretation-gold.json) were registered at
`ac84e15409aca3b9a1fa349fb40083b501ef214e`, before the instrument. These are
author-built public development cases, not independent expert labels or held-out accuracy.
Protocol byte SHA256: `fabd6b3a49088c7bb2b879600566d95a7692c1eccb4041882dce8f4669eef80a`.

The scope is deliberately narrow: the existing `fleet.premises` specialist's
clear-versus-human-review decision on the same offer, organisation and manifest inputs
as a future saved model response. It is **not** a claim that a large language model (LLM) improves allocation,
knapsack optimization, intake validation or the deterministic safety floor. Raw candidate
mistakes are scored before `Envelope.union`; the existing never-loosen control is reported
separately, not credited to the model. Gold and group labels never enter adapter inputs.

### Offline instrument

The [offline instrument](../scripts/evaluate_interpretation.py) reports fixed-denominator
risk capture (7), false positives on clear cases (3), unsafe clearance (11), abstention (14),
unknown-evidence capture (4), validity and every error/interruption. Capture means a review
decision, not proof that its explanation identified the right hazard. A model that refuses
everything gets full capture and full false positives, not perfect accuracy. Literal source
citations bind path/hash/quote, not semantic truth. Ungrounded review is counted explicitly.

Core CI runs this instrument check with a fake adapter and no model network adapter:

```bash
python scripts/evaluate_interpretation.py source-smoke --output evaluation-results
```

The `interpretation-source-only-<sha>-<run>` artifact retains all baseline/fake slots,
raw responses and source hashes, even after a failure. Tests deliberately break JSON, citations,
source identity, unsafe output and durable start ordering. Running is persisted before the
adapter starts; existing output directories are never overwritten. Artifacts have 90-day
retention. Source fake results are not actual Bedrock measurements or comparison wins.
An inert input-only plan can be prepared with `plan --output <new-directory>`; it performs no
evaluation or model call. `replay --receipts <captured.json> --output <new-directory>` is an
offline CI path for already-spent bytes only. Receipt hashes, ordered cases, all failures and
producer identity must be retained. Producer assertions are not authenticated AWS provenance.

### Prior evidence

The prior-evidence inventory is in the protocol. The historical
[backend proof](https://github.com/upgradedev/merismos-aws/actions/runs/34380636989)
at `a438849cd69ba25cb2dcd5679439ec9d1a303dac` contains model-tagged events and enriched
envelopes for `run-105bea9dede6`; it does not retain complete raw model responses or exact
contemporaneous read bytes. [The dated live run](live-run-2026-09-02.md) is also not a replayable comparison.
Neither was scored as new quality evidence or re-invoked. Usage, inference configuration and
dollar cost stay **UNKNOWN** where unmeasured.

### Bounded collector, not run

**Actual comparable model evaluation: NOT_RUN. No model-quality claim is made.** The frozen protocol is
unchanged. The separately gated [collector](../scripts/collect_interpretation.py) prepares
14 one-shot, text-only Converse calls to `eu.anthropic.claude-opus-5` in `eu-west-1`,
max output 768 tokens, thinking disabled, standard tier by omission, no cache fields or tools.
This is **evaluation-only source preloading, not the application's Strands agent/tool selection**.
The original premises system brief/instructions/question are preserved; the same frozen input
projection is supplied as an additional text block. No repair, continuation or fallback occurs.
Candidate citations are `[]`: the unchanged response contract supplies no model citation
sidecar. Clear responses without actual model citations therefore fail the frozen evaluator;
review responses remain visibly ungrounded. `supplied_source_provenance` only records delivered
bytes and is never passed as candidate proof. The separately preregistered citation candidate
below changes its own output contract, not this original candidate or ruler.

The [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5.html)
supports Converse but not runtime CountTokens. No CountTokens fallback is attempted. The input
bound is the full canonical serialized request's UTF-8 bytes plus **4096 framing tokens**, capped
at 16384 per case. This is a conservative byte-token/template **assumption requiring owner
review**, not measured tokenization or a provider guarantee. Media, tools, cache directives and
thinking are excluded. Returned usage exceeding either bound, missing request ID/usage, retries
or cache accounting stop the panel without refund; unknown outcomes retain worst-case cost.
Reference-only pricing is USD 5.50 per million input tokens and USD 27.50 per million output tokens, from the
[regional pricing table](https://platform.claude.com/docs/en/about-claude/pricing).
Those rates and the reference-cost artifact grant no authority and no budget.

Source CI runs `python scripts/collect_interpretation.py source-smoke --output bounded-evaluation`.
This exports exact per-case request bytes/hashes, max/sum sizes and reference-only worst costs,
then exercises the full durable collector-to-frozen-replay path with a conspicuously fake client.
The `bounded-evaluation-source-<sha>-<run>` artifact includes every raw synthetic response and
all 14 slots. Tests prohibit sockets/model construction and break grants, budget, run bindings,
expiry, writer durability, raw retention and unknown outcomes. No real model quality is inferred.

### Live authority prerequisite, 2026-09-11

A corrected read-only inventory on 2026-09-11 found `AWS_DEPLOY_ROLE_ARN` in the existing `aws` environment, not at repository scope, and traced historical deployment run 34380636989 to `merismos-github-deploy`, whose policy in `infra/bootstrap.sh` has no Bedrock actions.
Unless the secret's role identity has changed, missing `InvokeModel` permission blocks live collection.
The current secret value was not read for this page; reviewing the exact identity is the owner's job. A session
policy can restrict a role, never grant a missing base permission. The existing
secret/environment names are retained; `FRONTEND_RELEASE_ROLE_ARN` is never a fallback.
Missing role configuration produces explicit preflight refusal. The evaluation source creates no role,
trust, permission, secret or variable, and approving a budget does not authorize creating them.

### Activation contract

Original status-only candidate activation contract (NOT activated by source CI): after authority review, the owner
can configure repository
variables `MERISMOS_EVAL_GRANT_JSON` and `MERISMOS_EVAL_GRANT_SHA256`. The latter is SHA256 of
the former's parsed JSON serialized with sorted keys, compact separators and no nonfinite values.
The grant uses the `fake_grant` function's documented field shape, but must have authority
`PARENT_CONFIGURED_SINGLE_RUN`, a fresh grant ID, exact `binding(requests.json)`, conservative
finite decimal-string rates, an allocated `budget_usd` covering every worst-case call (at most USD 5),
`byte_bound_approved: true` and `standard_no_extra_charges: true`. The run object pins repository,
full workflow ref, the intended workflow run number (strings) and `run_attempt: "1"`; expiry
must be timezone-aware, still future and at most two hours away. The owner must reserve this full
allocation before configuring it. The worker does not infer
remaining aggregate funds. Changing source, model/config, protocol or request manifest denies it.
No actual grant, inference or live verification is established by this source preparation.

### Manual live job and recovery

After exact-source review, source CI and the budget reservation, **the owner only** may use:

```bash
gh workflow run ci.yml --repo upgradedev/merismos-aws --ref <reviewed-branch> \
  -f eval_grant_sha256=<owner-configured-canonical-grant-sha256>
```

Without the nonempty configured digest, the manual live job is skipped. Preflight runs before
credentials; it reuses the existing OIDC role with an inline session policy allowing only this
model's `bedrock:InvokeModel`, with no IAM/resource changes. The grant also pins the exact checked
out SHA and rejects dirty tracked code, wrong run number and reruns. A new output journal is
mandatory. A reservation and full request are create-only/fsynced before any SDK construction;
`total_max_attempts=1` disables SDK retry. Full decoded SDK response JSON, including AWS usage,
request ID and response metadata, is fsynced before parsing and flushed to stdout as backup.
It is not a raw HTTP packet capture. Every error/unknown outcome consumes the reservation;
actual priced usage is recorded separately and is not an AWS bill. The owner decides pricing,
the conservative bound assumption, any implicit-cache/account defaults and total-dollar safety.

The `bounded-live-<sha>-<run>-<attempt>` artifact uploads even after failure/cancellation when
the runner survives; stdout and disk cannot guarantee artifact recovery after infrastructure
loss. Keep the full reservation charged if evidence is lost. No run or call is auto-resumed.
Offline CI can reconstruct surviving create-only events without new inference:
`python scripts/collect_interpretation.py recover --journal <saved-journal> --output <new-directory>`.
Interrupted slots stay unknown, not not-run; all future slots remain not-run. The unmodified
evaluator still reports producer evidence as NOT_ESTABLISHED, not authenticated AWS quality.
The original collector changes no production app, deployment, IAM, database or model permission.
Independent cases and human adjudication remain necessary before any general quality claim.

## Separately preregistered cited candidate

This is source preparation only.

[Candidate registration](../evaluation/citation-candidate-v1.json) was committed at
`98f63b7081e0121051c3f6afd057fd5fe3a814c4` before implementation. Its byte SHA256 is
`415d1bd8f8f3a73cad848747e33afcc502a0c7f9f8f742c85ab4940d3d753ff1`.
The new hypothesis is narrowly that explicit citation output makes grounded clearance
representable under the existing ruler. It is not a measured improvement. Old protocol,
gold, fourteen cases, evaluator, original prompt/collector and all receipts are unchanged.
Both registrations must stay in the git history ahead of the code they register, so history on `main` must not
be squashed or rebased in a way that loses that order.

The [candidate](../scripts/citation_candidate.py) replaces only its own system instructions
with the registered answer-plus-citations contract. The same allowlisted source input and
question remain; gold and baseline answers are absent from requests. Source preloading is
still **evaluation-only Converse, not the application's Strands tool selection**. Model,
region, max output 768, thinking disabled and byte-bound assumptions remain as registered.
New request bytes/hashes and reference worst-cost plan are exported in source CI; old
candidate request manifests and grants do not authorize this new hypothesis.

Only fields actually present in a returned response can supply a candidate citation.
Path, current source hash, exact nonempty quote, strict integer start/end Unicode-character
span, known organisation and ownership of organisation-source records are checked first.
Then the model's answer and path/hash/quote projection go through the unchanged evaluator.
Projection never fills a missing citation from `supplied_source_provenance`. Full raw SDK-shaped
response and its hash precede parsing; original model text/hash and returned citation fields
remain in receipts. Invalid projection has a separately labelled invalid wrapper for the old
ruler and retains the original bytes, not a repaired answer or successful abstention.
Literal provenance still cannot prove semantic entailment: an injected instruction can be
literally cited yet support a wrong decision. The negative fixture preserves that wrong
candidate clearance separately from the deterministic governed refusal.

Existing source CI runs only:

```bash
python scripts/citation_candidate.py source-smoke --output citation-evaluation
```

The `citation-candidate-source-<sha>-<run>` artifact contains inert requests/reference costs,
all fourteen planned/started/raw-response slots, conspicuously fake responses and frozen-ruler
replay. The fake constructs citations solely as a plumbing fixture, never as evidence of model
selection or quality. `export` performs no evaluation; `replay --journal <source-fake-journal>`
uses retained source-fake bytes and a fresh output directory, never resumes calls. There is
**no live CLI or workflow activation for this new candidate**.
Core CI runs this source smoke on every pull request and on pushes to `main`, `feat/**` and `codex/**`; that is plumbing evidence, not a model result, and nothing is inferred from the original collector's green CI. Any live transport for this candidate needs a separate owner decision. No model-quality claim is made.
