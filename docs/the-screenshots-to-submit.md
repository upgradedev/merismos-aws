# The screenshots to submit, and why these ones

Devpost takes images alongside the description. This file says exactly which
frames to capture, from which URL, and what each one has to show for it to be
worth submitting.

**The test they have to pass.** A reviewer who did not build this opens the
image and writes down, in one sentence, what it shows the product *doing*. An
image fails if that sentence is "it shows the service exists". A console landing
page, a resource list, an empty table and a count of zero all fail for the same
reason: they prove something was created, not that anything was used.

That is not a hypothetical bar. Until 2026-09-08 the best frame in this product
could not be captured at all, because the page returned `503` after thirty
seconds. It answers in under half a second now.

---

## 1. The approval card. The one that carries the submission

Start a run and take the id it hands back:

```bash
curl -s -o /dev/null -w '%{redirect_url}\n' -X POST https://efnt6e0kv7.execute-api.eu-west-1.amazonaws.com/offer/offer-4471
```

Wait for it to finish, which takes a few minutes because four specialists read on
Claude Opus 5, then open the card at the run it produced:

```
https://efnt6e0kv7.execute-api.eu-west-1.amazonaws.com/approve/offer-4471?run=<the run id>
```

**Capture two frames from this page.**

The first is the section headed **What will be published**, showing the exact
bytes: the shares table, and under it *"Not receiving a share, and the rule that
decided it"* naming three organisations with a reason each. The sentence a
reviewer writes about this one is about apportionment being decided and explained,
which is the product.

The second is the table headed **What you are signing**: the network, the address
`records/offer-4471.md` marked readable by anyone with no account, the sha256, the
fifteen minute expiry, and the line saying the nonce is spent by a conditional
write. The sentence here is about a person authorising specific bytes, which is
the control.

**Do not crop the digest.** It is the thing that makes the claim checkable: the
writer recomputes it from the bytes that actually arrive, and a reader can match
it against the provenance row.

## 2. The intake, refusing a person

Open `https://efnt6e0kv7.execute-api.eu-west-1.amazonaws.com/offers/new`, fill it
in the way a coordinator would, and put a phone number in the note. Submit.

Capture the frame that shows the refusal at the top of the form **with everything
else still filled in**. The message reads that a published record never carries a
person, and asks for the food to be described rather than the people. Both halves
matter: the refusal, and the fact that nothing the coordinator typed was thrown
away.

At a phone width, because that is what a coordinator is holding.

## 3. The published record, in a window with no account

```
https://merismos-records-e6ac6047.s3.eu-west-1.amazonaws.com/records/offer-4471.md
```

A private window, no login, no AWS console. This is the answer to the question the
funder asks in March, and the whole point is that it needs nothing from anybody.

## What must never be in shot

The AWS account id. Any function URL that carries one. Any real organisation's
name. Everything in the corpus is invented and an image should not imply
otherwise. The terminal frames in the video are subject to the same rule.

## Before capturing, check these are still true

```bash
curl -s -o /dev/null -w '%{http_code} in %{time_total}s\n' https://efnt6e0kv7.execute-api.eu-west-1.amazonaws.com/approve/offer-4471
```

`404` in well under a second is correct: an approval covers the bytes one
particular run produced, and this route refuses rather than deciding again. **A
`503` means the site has regressed to re-running the chore inside the request, and
nothing should be captured until that is fixed.** The `still-up` workflow checks
the same thing twice a week.
