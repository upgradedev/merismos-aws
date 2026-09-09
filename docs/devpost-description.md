# Merismos — submission description draft

Merismos helps a community-food coordinator review a donation split and keep its reasons beside the collection handoff.

[Open Merismos](https://d2qnkmlhs7y5fp.cloudfront.net/). No account or installation is needed for
the synthetic sandbox. Choose **Add an offer → Try success**, edit the invented donation, work out
the split, review the exact plan and approve in sandbox. Then claim, schedule and explicitly
confirm a simulated collection.

## The problem and the product

A coordinator allocating a donation across community organisations needs to know who can accept
it, why another organisation was excluded and what remains unallocated. Merismos keeps those
decisions with the pickup commitments instead of making the coordinator reconstruct them later.
This is a synthetic demonstration with five invented organisations, not an adoption study.

Try refusal demonstrates a broken cold chain. Try correction demonstrates a refused phone-shaped
note that remains editable. All three examples submit to the real HTTP API. The dashboard shows
observed session outcomes and collection states, not estimated savings.

## What the sponsor supplies

The real **Strands Agents SDK** dispatches specialist tool calls. Its guard can stop a forbidden
tool before invocation. Removing Strands breaks the public sandbox journey; removing the guard
lets the negative-control call through. A separate deterministic gate checks the draft.

The public sandbox uses a scripted test model with no model network call, not Bedrock inference.
The internal AWS runner retains configured Bedrock `eu.anthropic.claude-opus-5`; a configuration
label alone does not establish a model call. An optional critic is not claimed as an active public
Lambda invocation. The application uses Lambda, DynamoDB, S3 and CloudFront, not AgentCore.

## Human control, evidence and limits

Live history is publicly read-only. A trusted coordinator authorizer, a current passing plan and
explicit exact consent are required for live changes. Typed names and client identity headers
cannot authorize publication. The public site supplies no coordinator sign-in integration.
The read-only legacy card preserves refused and stale drafts without making them publishable.

The writer uses conditional creation; a correction takes a new address and leaves original bytes
unchanged. Explicit authenticated recovery checks one saved attempt and can complete its receipt
without publishing again. A timeout is an unknown outcome, not a retry instruction.

The human-readable evidence bundle includes public source references, decision reasons, run and
workspace revision, provider/mode, record history, handoff and recovery limits. Hashes bind bytes,
not source truth or delivery. A coordinator may copy the bundle; Merismos sends no chat, email or
phone message. A saved allocation is not proof of collection.

No measured time saved, human active time, food rescued, compliance or beneficiary impact is
claimed. The contradictory historical offer-4471 record remains disclosed in the
[README](../README.md); it is not silently repaired. Current code, CI and live deployment are
separate evidence levels. New testbook cases and human signoff stay NOT_RUN until actually tested.

## Disclosure

The code was implemented for Merismos during the submission period, as the existing disclosure
records. The author brought prior fleet experience and a personal visual design direction; no prior
product code, customer data, configuration or assets were reused. Existing dependency licences,
MIT licence and video-tool contracts are preserved. See the [README](../README.md) for exact
validation, retained evidence IDs and deployment limitations. This file is a draft, not proof that
a submission form or video was published.
