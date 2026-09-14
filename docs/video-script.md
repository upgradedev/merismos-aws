# Merismos submission video

The video follows Maria, a fictional volunteer coordinator in a neighbourhood food network. One surplus offer
may suit several organisations, but their storage, transport and food-safety rules differ. Merismos helps Maria
reach an explained allocation and keep the collection handoff beside the decision. This matters because a split
without clear reasons can be unsafe, impossible to collect or hard for the network to review later.

The public workspace is [the deployed AWS application](https://d2qnkmlhs7y5fp.cloudfront.net/), not a mock-up.
Its five organisations and every offer shown in the video are synthetic. Nothing in the sandbox is published or
sent, and the video makes no claim about food rescued, time saved or beneficiary outcomes.

## Production contract

The target is 90 to 174 seconds, with seven measured beats of 3 to 40 seconds. ElevenLabs synthesises each beat
separately in CI, so one beat can be replaced without rebuilding the other six. The final gate checks the exact
frontend and backend commits independently, one-frame audio and video duration, caption order, caption bounds and
caption pixels in the encoded MP4.

The hook, architecture and close combine three source-controlled animated title scenes with the real architecture
and impact views. The allocation bars and architecture component selection add motion inside the product. The
central beats show the real public API journey from an editable offer through approval and simulated collection
confirmation. No presentation scene substitutes for product footage.

Before the measured timeline starts, capture selects **My sandbox**, opens **About this demo**, chooses
**Start over in a new sandbox**, and confirms **Yes, start fresh**. The capture then verifies the sandbox banner.
It never records **Shared demo records** or presents the known contradictory offer-4471 record as a correct plan.

## Seven screen and caption beats

| Beat | Screen and motion | Narration purpose |
| --- | --- | --- |
| **Hook** | Open the animated Merismos title scene, built from the repository banner, persona and problem statement. | Name Maria, the volunteer coordinator, the neighbourhood network and the consequence of an unsafe or uncollectable split. State that Merismos keeps checks, allocation and collection decision together. |
| **Surface** | Open the fresh **Dashboard**, choose **+ Add offer**, choose **Try success**, change the offer title and choose **Add to sandbox**. | Say explicitly that this is the live AWS application. Show that the offer is editable, the public HTTP API is used and the sandbox is synthetic and non-publishing. |
| **Trigger** | On **Decide**, choose **Work out the split**. Let the allocation bars animate, then bring **Approve this exact plan** into view. | Explain that deterministic rules run first. Eligible specialists use the **Strands Agents SDK** through bounded read-only tools, and a bounded solver proposes each share and remainder. State that the sandbox uses a fixed scripted model with no model network call. |
| **Live journey** | Expand **Read the exact record text**, tick the exact-allocation consent and choose **Approve in sandbox**. Open **Pickups**, choose **Claim this share**, tick the separate collection confirmation and choose **Confirm collection**. | Distinguish approval from collection. Complete the real journey from an editable offer to a recorded simulated handoff. |
| **Sponsor** | Open the animated architecture scene, then the deployed **AWS architecture** view. Select CloudFront and S3, the Lambda package and finally **Strands agents**, allowing the component transitions to complete. | Explain why Strands is load-bearing, the `BeforeToolCallEvent` guard and the guard-removal and SDK-removal tests. Name the private proof: run `34894779949`, backend `4bf2238`, model `eu.anthropic.claude-opus-5`. State that public visitors cannot start this Bedrock path. |
| **Evidence** | Return to the recorded decision, expand **Evidence bundle and recovery**, and keep the bundle in view. | Name the source references, reasons, run identity, revision, provider and history. Say that a digest binds bytes, not truth, and that authenticated authority is still required for live recovery and publication. |
| **Close** | Open **Impact and limits**, show the coordination problem, scroll to **What is not measured**, then finish on the animated URL scene. | Describe Merismos as a complete coordinator workflow without turning it into an impact claim. Close with the public sandbox URL and the unmeasured human-time, food-rescue and beneficiary outcomes. |

## Sponsor proof and claim boundaries

The public sandbox executes the real Strands agent loop with `scripted-planner/1.0.0`, a fixed tool sequence and a
fixed closing answer. It makes no Bedrock or external model network call. Private deploy proof
[34894779949](https://github.com/upgradedev/merismos-aws/actions/runs/34894779949) configured and exercised
`eu.anthropic.claude-opus-5` on backend `4bf2238dda6e9663cbae65ea14e1951ce7ed9cea`. A public request cannot start
that path because no coordinator authorizer is deployed.

Do not claim a separate critic Lambda, automatic messages, vehicle dispatch, compliance, measured savings or real
food rescued. A trusted public coordinator sign-in integration is not supplied. AWS permission and model probes
are IAM-authorised checks, never fabricated browser authorisation. The final MP4 is production evidence only when
the workflow's receipts and sync report pass for the exact deployed frontend and backend commits.
