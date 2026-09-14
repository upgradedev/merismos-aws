# Merismos documentation

Start with the [README](../README.md): what Merismos does, a short sandbox flow, the architecture overview, the cost boundaries and how to run it locally. Each page below answers one question.

## Current reference

- [Architecture](architecture.md): how one offer moves from intake to a recorded collection, drawn in two diagrams, and where each trust boundary sits.
- [Infrastructure](infrastructure.md): two diagrams of who can call what and who can touch which data, then every AWS resource, what each IAM role may do, what lives outside Terraform and what is not deployed.
- [Evidence and honest limits](evidence.md): the three evidence levels, current public acceptance, retained CI evidence, and what is not measured or not run.
- [Cost and latency](cost-and-latency.md): the historical partial estimate, what bounds a problem, the sandbox latency sample, the HTTP correlation headers and how the deployment comes down.
- [Release and validation](release-and-validation.md): a diagram of how a change reaches AWS, what each GitHub Actions workflow checks and how these documents are verified.

## Dated records

Each describes Merismos as it was on its date. They are kept as historical evidence, not as current guidance.

- [One live run, 2026-09-02](live-run-2026-09-02.md): one specialist reading the corpus with `eu.anthropic.claude-opus-5` on Amazon Bedrock.
- [Sandbox latency rows, 2026-09-13](measurements/sandbox-latency-2026-09-13.json): the raw rows behind the latency sample, taken with [the latency script](measurements/sandbox_latency.py).

## Submission material

- [Devpost description](devpost-description.md): the About copy, elevator pitch, Built With tags, testing instructions and media captions for the submission form.
- [Devpost thumbnail](assets/devpost-thumbnail.png): an upload-ready capture of the live synthetic Dashboard.
- [Architecture image](assets/overview.png): the upload-ready raster counterpart of the README architecture diagram.
- [Video script](video-script.md): the seven production beats, their exact screens and the claims they may make.

## Where to start in the code

The API and the Lambda handler are `src/merismos/api.py` and `src/merismos/handler.py`; approvals, the ledger and the specialist fleet are `approval.py`, `ledger.py` and `fleet.py` beside them. The React app is in `frontend/src/`, the IAM boundary in `infra/iam.tf` and the publication tests in `tests/regression/test_reliable_publication.py`. To run the offline demo, see [Run it locally](../README.md#run-it-locally).
