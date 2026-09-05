# The submission video

Under five minutes, public on YouTube. The rules ask for two things in one file:
a **demonstration of the working project** and a **pitch** covering the problem,
who it is for, and why it matters. The judging question is narrower and worth
quoting, because it is what this script is built to answer: *"Does the video
clearly demonstrate the project working end-to-end?"*

**Every shot is the real product.** No mockups, no slides pretending to be
screens. Where something is not deployed, the narration says so rather than the
picture implying otherwise.

**The live run is shown, and cut.** A four-specialist run takes about seven
minutes and the cap is five, so beat 3 shows the run starting and the page
reporting progress, then cuts to the finished decision. The cut is announced on
screen rather than hidden, because a recording that implies a seven minute job
took twenty seconds is the kind of small dishonesty this entry cannot afford.

Target 4:20. The cap is 5:00 and a recording that lands at 4:59 is a recording
that fails to build on the day.

---

## Beat 1. The problem, on the screen it actually happens on. 0:00 to 0:35

**Picture.** A phone-shaped frame. A group chat. Messages arriving:
*"Bakery has 240kg bread + veg, who can take it?"* ·
*"we can!"* · *"we're coming too"* · *"is anyone getting this?"*

**Narration.**
> Five small charities in one Athens neighbourhood share whatever food gets
> donated. A pantry, a night shelter, a school, a library breakfast club, a soup
> kitchen. None of them employs anybody to do this.
>
> An offer arrives, and whoever answers first takes it.

## Beat 2. What that costs. 0:35 to 1:05

**Picture.** Three cards, one at a time.
1. Two vans, same pallet.
2. A gift hamper, and a wine bottle inside it. Beside it: the night shelter's
   record, `alcohol_free_premises`, and the line about a residential recovery
   programme.
3. A calendar flipping September to March. An email: *"Please confirm what was
   distributed."*

**Narration.**
> Two vans drive to the same pallet.
>
> A crate of gift hampers goes to the shelter that runs a recovery programme,
> because the pallet label said "assorted ambient grocery" and nobody opened the
> manifest.
>
> And in March the funder asks what happened in September, and the record was a
> phone. That is the one that costs a small organisation its funding, for work
> it genuinely did.

## Beat 3. The product, live. 1:05 to 2:05

**Picture.** Screen recording of the deployed site. Open the offers list. Click
**Work out the split** on offer 4471, then **Ask the fleet**. The waiting screen
appears, counting specialists as they answer. Cut, with a caption saying how
long was removed. The decision screen: the shares table, then scroll to *"Not
receiving a share, and the rule that decided it"* with three organisations and
three reasons.

**Narration.**
> This is Merismos. It does the apportionment unattended and brings back one
> thing to approve.
>
> Four specialists wake. Each one is handed the network's filing and a question,
> not an answer, and each decides what to open. That takes minutes, so this is
> cut.
>
> Here is the split. And here is the part that matters: three members are not
> receiving a share, and each one is named with the rule that decided it. The
> library has no van and can carry fifteen kilos. That is on the screen, so
> nobody has to phone the library to find out.

## Beat 4. The case that decides whether a model earns its place. 2:05 to 2:50

**Picture.** Offer 4483. Show the offer's own fields: `category: ambient`,
`allergens: []`. Then the manifest, with wine, pork salami and hazelnut
highlighted. Then a two-row comparison on screen.

**Narration.**
> This offer declares category ambient and no allergens, and the donor described
> it honestly. They have no idea which of these five runs a recovery programme.
>
> The manifest says every hamper holds a bottle of wine and a pork salami, and
> some biscuits contain hazelnut.
>
> Read the declared fields alone: zero findings, nobody excluded, and wine
> reaches a recovery shelter and a school. Open the manifest: three findings,
> three organisations skipped, each with its reason. Both halves are pinned by
> tests.

## Beat 5. The one moment a person is in the loop. 2:50 to 3:30

**Picture.** The approval card. Scroll slowly: the exact bytes, then the sha256,
then *"What this approval does not authorise"*. Type a name. Click
**I have read these bytes. Publish them.** The published record appears. Then
open the public S3 URL in a clean window with no account.

**Narration.**
> Everything so far was autonomous. This is the only step that is not.
>
> You are approving these exact bytes. That digest is recomputed by a different
> identity before anything is written, so changing one character afterwards is
> refused. The approval lasts fifteen minutes and works once.
>
> And here is the record, public, readable by the funder with no account. That
> is the answer to the question asked in March.

## Beat 6. Why the Strands SDK is load-bearing, proven by removing it. 3:30 to 4:10

**Picture.** Split screen. Left: `guard.py`, the `BeforeToolCallEvent` callback
setting `cancel_tool`. Right: a terminal running the guard suite, `3 passed`.
Then the CI page showing the `guard-has-teeth` job. Then the ablation test
result: the hook removed, the same model reaching the tool.

**Narration.**
> Every refusal in this fleet happens inside the Strands tool dispatcher. The
> hook sets cancel_tool and the tool is never invoked. Remove the SDK and there
> is no dispatcher to refuse in.
>
> A gate nobody has watched go red is a gate nobody should believe. So one job
> asserts the reader is refused, and another removes the hook and asserts the
> same model then reaches the tool. The refusal is the guard, and not something
> else about the setup.

## Beat 7. What is not true yet. 4:10 to 4:20

**Picture.** Plain card, four lines of text.

**Narration.**
> Three honest limits. A run takes minutes, because a gateway request gets
> thirty seconds and a model read takes a hundred, so the chore runs in the
> background and the page waits. Private repositories are not supported. And the
> provenance ledger is append-only by interface rather than by storage policy,
> which the custody chain makes detectable rather than impossible.
>
> Merismos. Apportionment, and the record of how it was decided.

---

## Production notes

**Length.** Beats sum to 4:20 against a 5:00 cap. If a beat overruns, beat 2
loses its third card before anything else is cut; beats 5 and 6 are the two that
carry the submission and are never trimmed.

**Capture.** The deployed URL for beats 3 and 5, at a desktop width. The site
carries no external asset, so a capture is reproducible and will not change
because a font host did.

**Narration.** ElevenLabs, per beat, so one line can be re-cut without
rebuilding the whole thing. The key is present on this machine as a Windows user
variable and is not in this repository.

**What must never appear on screen.** The AWS account id, any function URL that
carries one, and any real organisation's name. Everything in the corpus is
invented and the video should not imply otherwise.

**The claim to check before publishing.** Every number spoken in this script has
to match the README and the description on the day it is recorded. The three
that move: the test count, the coverage figure, and the live URL.
