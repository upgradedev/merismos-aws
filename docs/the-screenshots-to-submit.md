# Merismos: evidence capture guide

For a community-food coordinator: [open the workspace](https://d2qnkmlhs7y5fp.cloudfront.net/),
choose **+ Add offer → Try success**, edit the invented fields, choose **Add to sandbox**, then
**Work out the split**, tick the consent box and choose **Approve in sandbox**. Record the deployed
frontend SHA from /release.json before capture.

Capture the real product at desktop and mobile widths, with the banner line "Sandbox · synthetic data · nothing is published" and the Today date chip visible:

1. An editable success flow, including recipient reasons (“Allocation & reasons”), exclusions
   (“Not receiving a share”) and the “Policy source:” line. On Decide at mobile width these sit in
   the offer stream below the “Your decision” pane, so scroll past it to capture them.
2. Try refusal: broken cold-chain evidence and no approval control.
3. Try correction: refused phone-shaped input, retained fields and the corrected successful intake.
4. The exact consent/digest and the distinct **Claimed**, **Scheduled** and **Confirmed collected**
   collection states, with the From offer to pickup stages Proposed, Approved, Scheduled and Collected.
5. Evidence bundle and recovery (on Decide with the offer selected, expand **Evidence bundle and
   recovery**): source references, run/revision, provider/mode, observed outcome, record history
   and explicit limits.

The sandbox executes the real HTTP API and Strands SDK with a scripted model, no model network
call and no public S3 publication. Live records are publicly read-only; never submit a legacy
anonymous POST to start a model run. An authorized internal AWS probe is a separate evidence
level and must be identified as such in any recording.

Use existing CI Playwright screenshots/traces as automated evidence, not human signoff.
No image proves food safety, source truth, compliance, time saved or food rescued. Do not crop
away limitations or label a digest as verified custody. Do not present the contradictory historic
offer-4471 record as a correct allocation; preserve its URL and disclosure in the README.

Strands is load-bearing on the sandbox tool-dispatch path; the deterministic gate is separate.
Configured Opus 5 is not a model-call receipt, and no screenshot of the sandbox shows a model call.
Live model calls are evidenced by deploy applies (each checks for a `specialist.answered` thread
entry with source "model" in `.github/workflows/deploy.yml`), not by any screen of the React
coordinator app. The optional critic is a tool-less Bedrock read made in-process by the reader-role
function running the chore, not a separate Lambda. It is off by default: `critic_model_id` defaults
to empty and the deploy workflow does not set it.
No real identities, credentials, account details or customer assets belong in shot.
The existing pre-existing-material and licence disclosures in the README also apply here.
New capture scope and human acceptance remain NOT_RUN until performed.
