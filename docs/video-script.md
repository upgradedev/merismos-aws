# Merismos: submission video draft

For a community-food coordinator, [open Merismos](https://d2qnkmlhs7y5fp.cloudfront.net/).
On the Dashboard choose **Start with this offer →**; on Decide choose **Work out the split**, tick
the consent box and **Approve in sandbox**; then open Pickups. To edit an invented donation, start
with **+ Add offer → Try success**, edit, choose **Add to sandbox**, then **Work out the split** and **Approve in sandbox**.
The sandbox uses the real HTTP API, a session saved in DynamoDB whose handle stops working after
24 hours, and a real Strands agent loop driven by the scripted model `scripted-planner/1.0.0`,
which makes no model network call. Live records are publicly read-only.

Target **90–174 seconds**, with seven beats of **3–40 seconds** each. These are production
bounds, not measured timing. The audio, video and caption gates of the video pipeline remain
authoritative. No recording or public upload is claimed by this draft.
Capture the actual release after its exact-SHA acceptance; an edited wait must disclose the elapsed
time removed. Capture preflight is mandatory: set **Workspace** to **My sandbox**, open **About this
demo**, choose **Start over in a new sandbox**, then **Yes, start fresh**. Verify the sandbox banner
and do not record **Shared demo records** or the known contradictory offer-4471 record.

| Beat | Actual product to capture |
| --- | --- |
| hook | Banner "Sandbox · synthetic data · nothing is published", the Dashboard’s “Next offer:” heading and **Start with this offer →**. Record it in a fresh sandbox: once the sandbox has a run or a record, the heading reads “Next open decision:” and the button **Continue my work →**. To reset, open **About this demo** in the page footer, choose **Start over in a new sandbox**, then **Yes, start fresh**. No staged customer story. |
| surface | On the Dashboard, **+ Add offer** opens “Add an offer”. **Try success** fills the editable fields, **Add to sandbox** sends the real request, and Decide opens on the new offer. |
| trigger | On Decide, **Go to next decision ↓** moves focus to “Your decision”, where the explicit **Work out the split** button shows **Working…** and the status “Saving through the backend. Please wait before making another change.” A sandbox run returns in the same request, so the run-step list is not shown. Scheduled escalation support is separate, not a recorded schedule firing. |
| live | In the sandbox, not live mode. **Try refusal**, **Add to sandbox** and **Work out the split**: a refused cold chain and no **Approve in sandbox** button. **Try correction** and **Add to sandbox**: the phone-shaped note is refused and the fields are kept. Remove the phone-shaped number from the note, choose **Add to sandbox** again, then **Work out the split** on the corrected offer. On its passing plan: **Read the exact record text**, tick the consent box, **Approve in sandbox**; then on Pickups **Claim this share**, tick “This collection actually happened in the simulation.” and **Confirm collection**. |
| sponsor | Open **About this demo** in the page footer: the provider line, then **Overview**, **How a donation moves** or **AWS architecture**, which show deterministic rules before eligible Strands agent loops. Show the CI guard and SDK-removal checks from the CI run, not as product footage. The sandbox uses a fixed scripted tool sequence and closing answer. A public request cannot start a live Bedrock run; name its exact model only after the frozen deploy proof confirms it. |
| evidence | On Decide with the offer selected, expand **Evidence bundle and recovery** under “Your decision”: sources, decision, run/revision, provider/mode, history, failure/recovery and limits. Hashes are not source truth. |
| close | On **Impact and limits** (page footer, **About this demo**): observed outcomes; the historical 10-sample sandbox latency check at frontend/backend `cb97c9e` (not a load test; live mode not measured); the absence of a reproducible total-AWS-cost claim; unmeasured human active time and benefits; then the workspace URL. |

`video/narration.json` holds the seven caption and speech beats under the same ids. Its close beat
does not speak the cost or latency figures; they appear on screen only. The existing video tool
schema/provider settings are preserved as production contracts, not app runtime providers.
`docs/video/cards.html` is only a labelled recording aid, never a substitute for product footage.

Do not claim a live critic Lambda, automatic sends, compliance, measured savings or real food
rescued. The known contradictory historical record stays disclosed; it is not silently repaired.
A trusted public coordinator sign-in integration is not supplied. AWS permission/model probes are
separate IAM-authorized checks, never fabricated browser authorization.

Current code, CI and live release evidence must be shown distinctly. New capture and human
acceptance remain NOT_RUN until performed. Pre-existing-material and dependency licence
disclosures are preserved in the README.
