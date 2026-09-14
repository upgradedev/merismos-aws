# Cost and latency

The headline figure and the sandbox claim are in [Cost and sustainability](../README.md#cost-and-sustainability).
This page holds how the figures were measured, what bounds a problem, and how the deployment comes down.

## Measured cost of the live proof

**The live proof in one deploy apply costs a median of $1.62.** This was measured read-only over the five deploy
applies between 2026-09-09 and 2026-09-13 that called the model. Each proof invokes the background runner twice: for
offer-4471, which the model answers, and for the refused offer-4477. How the cost splits between those two
invocations is not measured. At the AWS Pricing API's eu-west-1 on-demand prices the five proofs cost $1.44 to $1.78
each, with a median of $1.62, and Bedrock is about 99.6% of it. Taken column by column, the medians were 43 Bedrock
calls to `eu.anthropic.claude-opus-5`, 170,499 input and 23,712 output tokens, and 365.6 Lambda GB-seconds; no
single proof had all four. Other applications share the AWS account and CloudWatch's Bedrock totals are
account-wide, so CloudTrail was used to attribute every model call in those proof windows to the `merismos-reader`
role, which the runner runs under. Not measured: cache tokens, cold-start initialisation time, DynamoDB, S3,
CloudFront, Scheduler, logs, data transfer and the actual invoice. The functions are not attached to a virtual
private cloud (VPC), so there is no hourly NAT gateway or VPC endpoint charge.

The figure counts Bedrock tokens and Lambda only. The raw cost rows are not in this repository.

## What bounds a problem

These are the Terraform defaults; no tfvars file or workflow overrides them. Neither CloudWatch alarm has an alarm
action, so an alarm changes state in CloudWatch and notifies nobody.

| Control | Value | Set by |
| --- | --- | --- |
| API throttle | 10 requests per second, burst 20 | `judge_rate_limit`, `judge_burst_limit` |
| API integration timeout | 30 seconds, so live runs start in the background | `aws_apigatewayv2_integration.reader` |
| Reader concurrency | at most 5 at once | `reader_reserved_concurrency` |
| Background runner concurrency | at most 4 at once, in its own pool | `runner_reserved_concurrency` |
| Reader asynchronous retries | none | `aws_lambda_function_event_invoke_config.reader_retries` |
| Runner asynchronous retries | not configured, so Lambda's default applies: up to 2 retries after a function error such as the 900 second timeout | no `aws_lambda_function_event_invoke_config` for the runner |
| Error alarm | more than 5 reader errors in 5 minutes; no notification target | `aws_cloudwatch_metric_alarm.reader_errors` |
| Volume alarm | more than 500 reader invocations in one hour; no notification target | `judge_hourly_alarm` |
| Log retention | 14 days; provenance stays in DynamoDB | `log_retention_days` |

## Sandbox latency sample

On 2026-09-13, when the deployed frontend and backend were both at commit `cb97c9e`, one workstation
sent 10 samples, 15 s apart, to the sandbox. Each request opened a new TLS connection. There were 0
failures. This is not a load test, not browser render time and not Lambda cold-start time. Live mode
(Bedrock) was not measured. Raw rows: [sandbox-latency-2026-09-13.json](measurements/sandbox-latency-2026-09-13.json).
The script that took them, with the exact requests: [sandbox_latency.py](measurements/sandbox_latency.py).

| Request | Samples | Median | Max |
|---|---|---|---|
| `POST /api/sessions` | 10 | 337 ms | 1,224 ms |
| `GET /api/workspace?mode=sandbox` | 10 | 317 ms | 469 ms |
| `POST /api/offers/offer-4471/run`, scripted planner | 10 | 426 ms | 2,628 ms |

## HTTP request correlation

These headers correlate HTTP requests with Lambda invocations; they are not a cost measurement.

Responses under `/api/` carry a server-generated `x-merismos-request-id`, plus `x-merismos-lambda-request-id`
**only** from the actual Lambda context when available. `x-merismos-correlation-mode` distinguishes `lambda-context`
from `no-lambda-context`. The local real-HTTP harness has no Lambda context and never invents an AWS ID. Caller
headers, API business request IDs and authorizer values cannot supply these transport IDs. A small structured server
log records only both IDs, mode and response status; bodies, session tokens, user identity and paths are excluded.
A logging failure does not change a completed response.

Source measurement rows keep only these allowlisted response-header fields; adding them left the preregistered
twenty attempts, timing boundary, stages, summary and historical datasets as they were. Missing IDs stay
unavailable, never recorded as zero cost or as a successful correlation. The log and request-ID pair makes an exact
join to Lambda REPORT log lines possible, but the correlation code does not collect cloud logs, cover asynchronous
fleet invocations, measure Lambda cost, prove a service level or turn local timings into AWS performance. The
deployed backend returns these headers: every row of the 2026-09-13 sandbox latency sample carries a Lambda request
ID (`measurements/sandbox-latency-2026-09-13.json`), and the frontend release preflight requires `lambda-context`
mode. No join of those IDs to Lambda REPORT lines is recorded in this repository, so per-request duration and cost
correlation stay **NOT_RUN**. Collecting cloud logs for that join is the owner's decision.

The offline [REPORT exporter](../scripts/correlate_lambda_reports.py) follows Merismos's header and log contract. It
has no AWS client. After owner review, it can read an already-saved evidence bundle:

```bash
python scripts/correlate_lambda_reports.py --input saved-evidence.json --output new-report-directory
```

Input schema is `merismos-x1-report-input-v1`: independently retained `planned_requests` (1..1000), ordered
`requests`, exported `events` (at most 10000), and `expected_resource` containing exact unqualified `function_arn`,
numeric or `$LATEST` `function_version`, and non-wildcard `log_group_arn`. Each request has `ordinal`, HTTP `status`
and `response_headers` as name/value pairs, preserving duplicates. `capture_response` selects only the three
Merismos response headers; never pass request headers, cookies or reconstructed missing IDs. Each event preserves
`message`, `logGroupName`, `logStreamName` and independently exported `logGroupArn`. The latter is required: group
name alone cannot bind account or region. Only standard `/aws/lambda/<function>` groups and version-bearing Lambda
stream names are supported. Merismos's application log itself does not attest function ARN, version or code SHA.

Exactly one response ID to one structured `merismos.http.correlation` log to one matching Lambda text REPORT is
required, with matching status/resource/stream. Duplicate, missing, wrong-resource and ambiguous evidence is
refused, never resolved by choosing the first row. Dropped slots remain unmatched against the planned denominator;
extra slots invalidate coverage. Per-request duration, billed duration, memory and optional init/status fields
retain exact reported values. HTTP error responses can correlate; coverage is not business success. Every row and
summary keep USD cost `null`. No all-service cost, async-fleet coverage or SLA is inferred. JSON platform reports
and unsupported text variants remain incomplete.

Input is bounded to 10 MiB and saved before parsing in a create-only output directory alongside result and hash
manifest; parse failures retain original bytes. Hashes bind supplied bytes, not their AWS origin. The owner must
keep the original exports separately. Existing source timing datasets without Lambda IDs cannot be upgraded into AWS
evidence. Focused pytest controls run in core CI; a REPORT join against real AWS logs stays **NOT_RUN**. The
exporter changes no frontend or API behavior, activates no workflow, grants no privilege and leaves the measurement
protocol as it is.

## How long it stays up, and how it comes down

The rules require the entry to stay reachable until judging ends on 2026-10-08 17:00 PT. `still-up.yml`
fetches the API Gateway URL and one published record anonymously every Monday and Thursday at 09:00 UTC;
nothing on a schedule checks the CloudFront URL. To take the deployment down, dispatch `deploy.yml` with
`dry_run=no` and `keep=no`: it applies, runs the same proofs, then runs `terraform destroy` in the same
job, whether or not the proofs passed. With `destroyable` at its default of true the buckets are emptied
too. The job then lists every remaining `merismos` Lambda, table, bucket, role, queue and schedule group,
and fails if any is left apart from the bootstrap state bucket and deploy role. The frontend stack's site
bucket (`merismos-web-<account>-<region>`) and release role (`merismos-frontend-release`) are outside
Terraform but match the listing, so while that stack exists a run with `keep=no` fails with "teardown
left resources behind". [What lives outside Terraform](infrastructure.md#what-lives-outside-terraform)
has the full list. `deploy.yml` never deletes the CloudFormation stack `merismos-frontend`: after a
teardown its CloudFront distribution still serves the static app from the site bucket, and no workflow or
script in this repository deletes that stack.
