# Merismos, for the Devpost submission form

Staged here so the description, the README and the video cannot drift apart.
Paste the sections below into the matching fields.

---

## The live demo

**https://efnt6e0kv7.execute-api.eu-west-1.amazonaws.com**

No account, nothing to install. Press **Ask the fleet** on any offer.

## The one sentence

**Merismos apportions donated food between five charities and publishes the record that says who
was skipped and why.**

---

## Inspiration

Five small organisations in one Athens neighbourhood share whatever gets donated: a food pantry, a
night shelter, a school, a library breakfast club and a soup kitchen. None of them employs anybody
to do this.

An offer arrives in a group chat and whoever answers first takes it. That produces three failures,
and all three are ordinary rather than dramatic.

Two vans drive to the same pallet.

A crate of seasonal gift hampers goes to the night shelter, and each hamper holds a bottle of wine.
The shelter runs a residential recovery programme. Nobody read the manifest, because the pallet
label said "assorted ambient grocery" and the offer's own allergen field was empty.

And in March the funder asks what happened in September, and nobody can answer, because the record
was a phone.

The third one is the expensive one. Small organisations lose funding over evidence they cannot
produce about work they genuinely did.

## The problem, in somebody else's numbers

Every organisation in this project is invented. The problem is not. From the European Food Banks
Federation's own impact page, read 2026-09-05: across 28 European countries, **42,796 charitable
organisations** receive redistributed food from **480 food banks**, and of the **109,421** people
doing that work, **92% are volunteers**.

Ninety two per cent volunteers is why "nobody here employs anybody to do this" is a fact rather than
a premise. Ninety receiving organisations per food bank is why apportionment between independent
organisations is the shape of the sector rather than an edge case.

What those numbers do not establish is that these five would adopt this tool. Nobody outside this
build has used it, and no figure closes that.

## What it does

A coordinator types what the donor told them into a form on their phone: what it is, who is giving
it, how much, when it is collected. A fleet of specialists wakes, reads the network's own filing, and
works out the split. A deterministic gate checks the draft. Then it stops, and one person reads the
exact bytes and approves them.

The offers are the network's own, not ours. That mattered enough to change the architecture: filing
an offer is a write, and the identity serving the public form cannot write. It validates what was
typed, tells the coordinator immediately if a phone number or an instruction to the fleet is in
there, and then asks the one identity that holds the write. That identity rebuilds the offer from the
form rather than trusting what it was handed, and S3 itself refuses to let an intake overwrite an
offer that has already been decided about.

Everything before the approval is autonomous. The approval is the end, not a stall in the middle.

What gets published is the part that matters: **who received what, and who was skipped and by which
rule.** A decision nobody can see is a decision that gets re-litigated by phone.

## The case that shows why a model earns its place

`offer-4483` is a wholesaler clearance. Its declared fields say category `ambient`, `allergens: []`,
long dated. Nothing unusual, and the donor described it honestly: they have no idea which of these
five runs a recovery programme.

The manifest says each of the forty gift hampers holds a small pork salami and a 375ml bottle of red
wine, and that some biscuit lines contain hazelnut.

| Reading | Findings | Organisations excluded | What happens |
|---|---:|---:|---|
| declared fields only | 0 | 0 | wine reaches a recovery shelter and a school |
| after opening the manifest | 3 | 3 | the three who cannot accept it are skipped, with the reason |

Both halves are pinned by tests that need no credentials, including one asserting the offer's own
fields mention none of those words, so the comparison cannot quietly become trivial later.

**You can run this yourself on the live site.** Press Ask the fleet. Four specialists wake on Claude
Opus 5. Each chooses what to open.

One recorded run found **two things the deterministic rules do not**. Undeclared milk and gluten.
And a contradiction between the donor's whole-lot condition and the network's own 40% ceiling, which
no rule here compares. Neither was planted for it to find.

## How we built it

The **Strands Agents SDK** is load-bearing, and the specific reason is worth one sentence: every
refusal in this fleet happens inside Strands' tool dispatcher. `BeforeToolCallEvent` fires, a hook
sets `cancel_tool`, and the tool is never invoked. Remove the SDK and there is no dispatcher to
refuse in, and the guarantee becomes a sentence in a prompt asking a model to behave.

That is proven in both directions. One CI job asserts the reader is refused `publish_record`.
Another **removes the hook and asserts the same model then reaches the tool**, so the refusal is
attributable to the guard and not to something else about the setup. A third job fails the build if
either suite silently skips.

Three AWS Lambda functions under three IAM roles, one package. The identity that reads the filing
holds no authority to publish, and AWS refuses it rather than our code doing so. `/identity` proves
that live: it **attempts** the write and reports what AWS said.

The approval binds exact bytes by sha256, expires in fifteen minutes, and is spent by a conditional
write, so one approval authorises one publish and cannot be replayed.

A parked decision wakes on the day, through an EventBridge Scheduler one-shot schedule that deletes
itself after firing.

## Challenges we ran into

**Public Lambda Function URLs are refused in our AWS account.** Not a misconfiguration: we ruled out
the auth type, the resource policy, service control policies, resource control policies, declarative
policies and the management-account question, then settled it by deploying a two-line throwaway
Lambda with a public URL, which was also refused. The judge path runs behind API Gateway instead.

**An HTTP API integration times out at 30 seconds and that cannot be raised.** A specialist reading
with Claude Opus 5 takes about 100. So the first deployment ran the deterministic rules, and a
review caught the consequence: take the SDK away and the deployed path still worked. Our strongest
claim was true of the repository and false of the demonstration.

The fix was to stop making the run synchronous. Pressing the button starts a chore on a background
invocation, which has its own 900 second budget, and the page polls the provenance thread. The
thread was already the memory and the audit trail; it is now also the progress bar, and there is no
second store.

**The first deployment found three defects that every green plan had missed**, including a Function
URL that was public in configuration and refused in practice, and a teardown that left six resources
standing because versioned buckets will not delete. An apply that cannot be reversed is a bill.

## What we learned

The lesson that cost the most: **a green test suite can agree with a bug for as long as the bug
exists.** Our read budget was shared across four specialists and spent in arrival order, which is
alphabetical. The first took ten of twelve; the rest ran with nothing and each spent a model call to
report that it had been starved. They reported it correctly, which is the safety property working,
and the design was still wrong. Only a deployed multi-specialist run showed it.

And one about honesty: this project's own documentation claimed an architecture the code did not
have. We found it with a check that compares every capability word in the docs against the source,
before the repository was public. A gate you only point outward is not a gate.

## What's next

Private repositories are not supported. Reads use the public API with no credential, deliberately:
a read path that needs a token is a read path that can be used to write.

The provenance ledger is append-only by interface rather than by storage policy. A custody chain
over it makes an edit from outside our code detectable. It does not make a row immutable, and the
site says so on the page that shows the chain.

---

## Built with

`strands-agents` · Amazon Bedrock (`claude-opus-5`, `amazon.nova-pro`) · AWS Lambda · API Gateway ·
DynamoDB · Amazon S3 · EventBridge Scheduler · AWS Secrets Manager · IAM · Terraform · Python 3.13

## Pre-existing components, disclosed

Every line of code in this repository was written during the submission period.

The author has built agent fleets before, and the shape of this one is informed by that. No code was
carried across. Nothing here is derived from a deployable product.

Every organisation, person, offer and donor in the corpus is invented. No real charity's data or
name appears anywhere.
