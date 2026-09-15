# Evidence and honest limits

Offline CI, frontend release identity and live AWS acceptance are three different evidence levels.
The README keeps the short version under [What is real and what is demonstrated](../README.md#what-is-real-and-what-is-demonstrated).

## Evidence levels

Each level proves something different:

- Offline CI runs the Python suite, and runs the Playwright journeys against the local HTTP harness, with no AWS
  credentials. It shows what the source does, not what AWS runs.
- Frontend release identity is the commit marker in the served HTML and `release.json`. Every push to `main` starts
  the guarded release pipeline, but only a successful full pipeline republishes them. They show which frontend build
  is served, not which backend answers.
- Live AWS acceptance runs the desktop and mobile Playwright journeys against CloudFront and publishes a receipt
  that records the answering backend's commit. It is scripted synthetic AWS software evidence, not a Bedrock model
  invocation or human acceptance.

The [acceptance testbook](../frontend/UAT.testbook.html) and [machine-readable cases](../frontend/UAT.testbook.json)
keep historical evidence separate from current scope. Changed cases begin at **NOT_RUN** until
actual CI evidence exists. Human acceptance remains **NOT_RUN** until a person signs off.

## What the dashboard counts

Dashboard quantities and outcomes are derived from the available API session snapshot. Units are
not combined. Draft allocations, recorded decisions, refusals, corrections and confirmed collections
are distinguished. Unknown/inconsistent projection rows are excluded with a visible reason.

## Evidence bundles and the pickup manifest

On **Decide**, with an offer selected, expand **Evidence bundle and recovery** and choose
**Copy evidence bundle** to copy the current decision, logical source references from the current API snapshot,
run, workspace revision,
provider/mode, record history, handoff and limits. Copying does not send a message, approve anything
or change custody status.

**Pickup manifest · copy or download** gives the coordinator a plain-text `.txt` handoff with
quantities, dates, allergens, reasons, run/plan identity, before/after changes and collection states.
It sends no message and certifies no recipient receipt.

## Current public acceptance

[Open the anonymous acceptance page](https://d2qnkmlhs7y5fp.cloudfront.net/acceptance.html)
or [read its latest successful JSON receipt](https://d2qnkmlhs7y5fp.cloudfront.net/acceptance.json).
The page compares the actual served root HTML commit marker and `release.json` with the receipt's recorded commit,
checks the identical retained run receipt and requires an observation within 24 hours. Missing or
malformed proof is pending or unknown; stale or mismatched proof is historical, never a current pass.

Successful preflight, product journeys and postflight produce an allowlisted aggregate from the
current run's Playwright `test-results/e2e.xml`, with zero failures/skips. Acceptance run
[34909237304, attempt 1](https://github.com/upgradedev/merismos-aws/actions/runs/34909237304/attempts/1) recorded 40 of 40
desktop/mobile product journeys (`npm run test:e2e -- --forbid-only --project=desktop --project=mobile`).
The offline-only `mobile-webkit` project is not part of that live run. Retry, rerun and flaky
result tags are rejected even when summary counters report zero failures.
Proof-display fixtures have a separate source-only suite and `proof-junit.xml`; their counts never
enter the AWS product totals. A separate read-only browser job checks the actual published page.
The receipt says `workflow_status=NOT_ASSERTED`, because publication precedes workflow completion.
It does not include the separate deploy-time writer read-capability probe (ME18), which passed for backend
`4bf2238` in [apply run 34894779949](https://github.com/upgradedev/merismos-aws/actions/runs/34894779949).
That probe asserted read-only S3 corpus freshness and DynamoDB custody-head permissions; it was not a publication
drill or human signoff. Human acceptance testing (UAT) and the separate authenticated coordinator publication and
recovery drill remain **NOT_RUN**.

Each immutable `/acceptance/runs/<run-id>-<attempt>.json` contains sanitized aggregate counts,
statuses, timestamps, source and run references only. Publication creates it conditionally or
verifies identical existing bytes, then updates `/acceptance.json` only while the S3 and served
root HTML and manifests still match. Manifest-only partial deployments cannot become current proof.
Producer artifact name and attempt are retained as job outputs: a publisher-only retry uses the
original tested attempt, rather than relabeling its counts. Frontend deployment never deletes
history or ships receipt files from its build.
Receipts are published with the private frontend bucket, its uncached static behavior and the release role
that only `main` can assume; publishing them needed no extra IAM permission. Both browser jobs have
`contents:read` only; credentials live solely in the separate publisher. Main release and proof publication
share one lock, and stale dispatches fail.

### Backend identity in the receipt

The receipt takes the answering backend's commit from `GET /api/version` observations of CI-packaged metadata
before and after the journeys, and refuses to build if the two differ.
Older deployments remain explicitly **unavailable**, and schema-1 receipts
retain their original basis. Anonymous `/identity` attempts Secrets Manager and conditional S3 capability probes;
`/identity?all=1` also invokes the evaluator and writer. It therefore causes throttled AWS work and is never used
for this version read. Its fixed private probe keys bound durable version growth, but do not make the endpoint a
free metadata read. Runtime environment values and the frontend SHA cannot supply the backend identity. A known
commit identifies the answering function, not fleet-wide parity.
This is scripted synthetic AWS software evidence, not a Bedrock model invocation, human acceptance or measured food rescue.

## Retained CI evidence

Earlier accepted AWS evidence is preserved without executing or extracting the original ZIP:
source run `34360378251`, artifact `10107806322`; archive run
[34374515388](https://github.com/upgradedev/merismos-aws/actions/runs/34374515388),
artifact `10113274903`. Its manifest contains original IDs, source commit and ZIP SHA256.
The archive job runs only when Frontend verification is dispatched by hand with `archive_previous_acceptance`; it has
already run, and routine CI skips it.
No original artifact was deleted. Artifact retention is 90 days, not permanent storage.

## Historical records

The first published [offer-4471 record](https://merismos-records-e6ac6047.s3.eu-west-1.amazonaws.com/records/offer-4471.md)
contains a known contradictory allocation. It is preserved as historical evidence, not presented as
a correct plan. It is not repaired automatically.
The [dated model run](live-run-2026-09-02.md) describes its original checkpoint, not the current release.

## Observed and still unverified

- Human active time, time saved, food rescued, beneficiary impact and adoption: not measured.
- Human acceptance testing: NOT_RUN until a person signs off.
- The deploy-time writer read-capability probe (ME18): PASS_AUTOMATED_AWS for backend `4bf2238` in
  [apply run 34894779949](https://github.com/upgradedev/merismos-aws/actions/runs/34894779949), with retained
  artifact `writer-read-capabilities-34894779949`. It checked read-only permissions, not publication or human
  signoff.
- The separate authenticated coordinator publication and recovery drill: NOT_RUN.
- Real-device Safari testing and a timed first-use test: not run.
- Cost not measured: cache tokens, cold-start initialisation, DynamoDB, S3, CloudFront, EventBridge Scheduler, CloudWatch Logs, data transfer, GitHub Actions minutes, free tier and the actual invoice.
- Latency of live runs on the current release: not measured.
- A comparable model evaluation: NOT_RUN. No model-quality claim is made.
