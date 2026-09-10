"""CI-only aggregate acceptance receipts; no scenario contents or runtime probes."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from frontend_publish import aws
from frontend_smoke import fetch
from backend_version import UNKNOWN, observe, stable_backend, valid_commit

REPOSITORY = "upgradedev/merismos-aws"
ORIGIN = "https://d2qnkmlhs7y5fp.cloudfront.net/"
SHA = re.compile(r"[0-9a-f]{40}")
NUMBER = re.compile(r"[1-9][0-9]*")
MIN_PRODUCT_JOURNEYS = 24  # Existing desktop/mobile product suite; added journeys are allowed.
BACKEND_BASIS = (
    "Unavailable: /identity attempts Secrets Manager reads and S3 PutObject; "
    "no harmless deployed build-identity endpoint exists in the inspected source. "
    "No backend probe or SHA parity is claimed."
)
UNKNOWN_BACKEND_BASIS = "Backend version unavailable from GET /api/version; no backend commit or fleet parity is claimed."
KNOWN_BACKEND_BASIS = "Packaged backend commit observed via GET /api/version before and after the journeys; identifies the answering backend only, not every fleet function or frontend parity."
LIMITS = (
    "Synthetic scripted-planner/1.0.0 through real Strands and AWS HTTP persistence. "
    "Product journeys only; proof-display fixtures and post-publication proof checks are counted separately. "
    "No Bedrock model calls, real food rescue, "
    "authenticated live-coordinator publication (ME18), or human UAT."
)
FIELDS = {"schema_version", "application", "environment", "frontend_commit", "backend_commit",
          "backend_basis", "run_id", "run_attempt", "run_url", "observed_at", "preflight",
          "journeys", "postflight", "junit", "human_uat", "mode", "limits", "workflow_status"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def utc_now():
    return datetime.now(timezone.utc)


def validate(receipt, now=None):
    require(isinstance(receipt, dict) and set(receipt) == FIELDS, "unexpected receipt fields")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] in {1, 2}, "schema")
    require(receipt["application"] == "merismos" and receipt["environment"] == "live_aws", "scope")
    require(isinstance(receipt["frontend_commit"], str) and SHA.fullmatch(receipt["frontend_commit"]), "frontend SHA")
    if receipt["schema_version"] == 1:
        require(receipt["backend_commit"] == "unavailable" and receipt["backend_basis"] == BACKEND_BASIS, "backend basis")
    else:
        require((receipt["backend_commit"] == "unavailable" and receipt["backend_basis"] == UNKNOWN_BACKEND_BASIS)
                or (valid_commit(receipt["backend_commit"]) and receipt["backend_basis"] == KNOWN_BACKEND_BASIS), "backend basis")
    for key in ("run_id", "run_attempt"):
        require(isinstance(receipt[key], str) and NUMBER.fullmatch(receipt[key]), key)
    require(receipt["run_url"] == f"https://github.com/{REPOSITORY}/actions/runs/{receipt['run_id']}/attempts/{receipt['run_attempt']}", "run URL")
    require(all(receipt[key] == "SUCCESS" for key in ("preflight", "journeys", "postflight")), "incomplete phases")
    totals = receipt["junit"]
    require(isinstance(totals, dict) and set(totals) == {"total", "passed", "failed", "skipped"}, "JUnit fields")
    require(all(type(value) is int and value >= 0 for value in totals.values()), "JUnit counts")
    require(totals["total"] >= MIN_PRODUCT_JOURNEYS and totals["total"] == totals["passed"]
            and totals["failed"] == totals["skipped"] == 0, "JUnit not clean or below 24 product journeys")
    require(receipt["human_uat"] == "NOT_RUN" and receipt["mode"] == "synthetic_scripted", "mode/signoff")
    require(receipt["limits"] == LIMITS and receipt["workflow_status"] == "NOT_ASSERTED", "limits/workflow")
    observed = receipt["observed_at"]
    require(isinstance(observed, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", observed), "observation time")
    timestamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    age = ((now or utc_now()) - timestamp).total_seconds()
    require(0 <= age <= 86400, "observation is future-dated or older than 24 hours")
    return receipt


def junit_counts(path):
    data = Path(path).read_bytes()
    require(0 < len(data) <= 10_000_000 and b"<!DOCTYPE" not in data and b"<!ENTITY" not in data, "unsafe or empty JUnit")
    root = ElementTree.fromstring(data)
    require(root.tag in {"testsuites", "testsuite"}, "JUnit root")
    identities = set()

    def identify(element, lineage=()):
        tag = element.tag.rsplit("}", 1)[-1].lower()
        require(not any(word in tag for word in ("flaky", "rerun", "retry")), "JUnit contains retry or flaky results")
        for key, value in element.attrib.items():
            if key.lower() in {"retries", "retry", "reruns", "flaky"}:
                require(value.lower() in {"0", "false"}, "JUnit contains retry or flaky metadata")
        require(element.get("status", "").lower() not in {"flaky", "retry", "rerun"}, "JUnit retry status")
        if element.tag in {"testsuites", "testsuite"}:
            # Project/hostname belongs to the identity: desktop and mobile may
            # intentionally share testcase classname/name.
            lineage += (tuple(element.get(key, "") for key in ("name", "hostname", "id", "package")),)
        if element.tag == "testcase":
            require(bool(element.get("name")), "unnamed JUnit case")
            identity = (lineage, element.get("classname", ""), element.get("name"))
            require(identity not in identities, "duplicate JUnit case in the same project")
            identities.add(identity)
        for child in element:
            identify(child, lineage)

    identify(root)
    cases = list(root.iter("testcase"))
    require(bool(cases), "JUnit has no executed cases")
    def counts(items):
        failed = sum(case.find("failure") is not None or case.find("error") is not None for case in items)
        skipped = sum(case.find("skipped") is not None for case in items)
        return {"total": len(items), "passed": len(items) - failed - skipped, "failed": failed, "skipped": skipped}
    for suite in root.iter():
        if suite.tag not in {"testsuites", "testsuite"}:
            continue
        children = list(suite.iter("testcase"))
        require(bool(children), "empty JUnit suite")
        expected = {"tests": len(children), "failures": sum(c.find("failure") is not None for c in children),
                    "errors": sum(c.find("error") is not None for c in children),
                    "skipped": sum(c.find("skipped") is not None for c in children)}
        for key, value in expected.items():
            if key in suite.attrib:
                require(re.fullmatch(r"[0-9]+", suite.attrib[key]) and int(suite.attrib[key]) == value, "JUnit summary disagrees with cases")
    return counts(cases)


def source_guard(sha, env, current_main):
    require(SHA.fullmatch(sha or ""), "full SHA required")
    require(env.get("GITHUB_REPOSITORY") == REPOSITORY and env.get("GITHUB_REF") == "refs/heads/main", "main-only source")
    require(env.get("GITHUB_SHA") == sha == current_main, "stale dispatch or source mismatch")


def build_receipt(junit, sha, env, now=None, before=None, after=None):
    now = now or utc_now()
    backend = stable_backend(before if before is not None else UNKNOWN,
                             after if after is not None else UNKNOWN)
    receipt = {
        "schema_version": 2, "application": "merismos", "environment": "live_aws",
        "frontend_commit": sha, "backend_commit": backend or "unavailable",
        "backend_basis": KNOWN_BACKEND_BASIS if backend else UNKNOWN_BACKEND_BASIS,
        "run_id": env.get("GITHUB_RUN_ID"), "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "run_url": f"https://github.com/{REPOSITORY}/actions/runs/{env.get('GITHUB_RUN_ID')}/attempts/{env.get('GITHUB_RUN_ATTEMPT')}",
        "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **{key: env.get(key.upper(), "").upper() for key in ("preflight", "journeys", "postflight")},
        "junit": junit_counts(junit), "human_uat": "NOT_RUN", "mode": "synthetic_scripted",
        "limits": LIMITS, "workflow_status": "NOT_ASSERTED",
    }
    return validate(receipt, now)


def canonical(receipt):
    return (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()


def html_commit(body):
    # frontend_publish emits this exact marker. Missing or duplicate markers fail closed.
    matches = re.findall(rb'<meta name="application-commit" content="([0-9a-f]{40})">', body)
    require(len(matches) == 1, "root HTML identity missing or ambiguous")
    return matches[0].decode("ascii")


def publish(receipt, env, current_main, command=aws, request=fetch, now=None, version_request=None):
    validate(receipt, now)
    sha = receipt["frontend_commit"]
    source_guard(sha, env, current_main)
    producer_attempt = env.get("PRODUCER_RUN_ATTEMPT", "")
    current_attempt = env.get("GITHUB_RUN_ATTEMPT", "")
    require(NUMBER.fullmatch(producer_attempt) and NUMBER.fullmatch(current_attempt)
            and int(producer_attempt) <= int(current_attempt), "invalid producer attempt")
    require(receipt["run_id"] == env.get("GITHUB_RUN_ID") == env.get("PRODUCER_RUN_ID")
            and receipt["run_attempt"] == producer_attempt, "artifact does not match producer identity")
    require(env.get("PRODUCER_ARTIFACT") == f"acceptance-proof-{receipt['run_id']}-{producer_attempt}", "artifact name does not match producer")
    reply = command("cloudformation", "describe-stacks", "--stack-name", "merismos-frontend", "--region", "eu-west-1")
    outputs = {item["OutputKey"]: item["OutputValue"] for item in reply["Stacks"][0]["Outputs"]}
    bucket = outputs["FrontendBucket"]
    require(re.fullmatch(r"merismos-web-[0-9]{12}-eu-west-1", bucket), "not Merismos frontend bucket")
    require(outputs["FrontendUrl"].rstrip("/") + "/" == ORIGIN, "unexpected frontend origin")
    key = f"acceptance/runs/{receipt['run_id']}-{receipt['run_attempt']}.json"
    with tempfile.TemporaryDirectory(prefix="merismos-acceptance-") as tmp:
        payload = Path(tmp) / "receipt.json"
        payload.write_bytes(canonical(receipt))

        def release_matches():
            # Origin and CDN must agree under the shared publication lock. No /identity call.
            release = Path(tmp) / "release.json"
            command("s3api", "get-object", "--bucket", bucket, "--key", "release.json", str(release), "--region", "eu-west-1")
            require(json.loads(release.read_bytes())["commit"] == sha, "S3 release mismatch")
            index = Path(tmp) / "index.html"
            command("s3api", "get-object", "--bucket", bucket, "--key", "index.html", str(index), "--region", "eu-west-1")
            require(html_commit(index.read_bytes()) == sha, "S3 root HTML mismatch")
            status, _, body = request(ORIGIN + "release.json")
            require(status == 200 and json.loads(body)["commit"] == sha, "deployed release mismatch")
            status, _, body = request(ORIGIN)
            require(status == 200 and html_commit(body) == sha, "served root HTML mismatch")
            if valid_commit(receipt["backend_commit"]):
                observed = observe(ORIGIN) if version_request is None else observe(ORIGIN, version_request)
                require(observed["commit"] == receipt["backend_commit"], "backend changed before publication")

        release_matches()
        args = ("s3api", "put-object", "--bucket", bucket, "--body", str(payload),
                "--content-type", "application/json", "--region", "eu-west-1")
        try:
            command(*args, "--key", key, "--if-none-match", "*", "--cache-control", "public,max-age=31536000,immutable")
        except subprocess.CalledProcessError as error:
            if "PreconditionFailed" not in (error.stderr or ""):
                raise
            existing = Path(tmp) / "existing.json"
            command("s3api", "get-object", "--bucket", bucket, "--key", key, str(existing), "--region", "eu-west-1")
            require(existing.read_bytes() == payload.read_bytes(), "immutable receipt already exists with different bytes")
        release_matches()
        command(*args, "--key", "acceptance.json", "--cache-control", "no-store,max-age=0")
    return {"receipt_url": ORIGIN + key, "latest_url": ORIGIN + "acceptance.json", "workflow_status": "NOT_ASSERTED"}


def current_main():
    return subprocess.run(["gh", "api", f"repos/{REPOSITORY}/commits/main", "--jq", ".sha"],
                          check=True, capture_output=True, text=True).stdout.strip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["guard", "create", "publish"])
    parser.add_argument("--sha", required=True)
    parser.add_argument("--junit", default="frontend/test-results/e2e.xml")
    parser.add_argument("--receipt", default="acceptance-proof/receipt.json")
    parser.add_argument("--preflight")
    parser.add_argument("--postflight")
    args = parser.parse_args()
    if args.action == "guard":
        source_guard(args.sha, os.environ, current_main())
    elif args.action == "create":
        require(args.preflight and args.postflight, "both flight observations are required")
        flights = [json.loads(Path(path).read_bytes()) for path in (args.preflight, args.postflight)]
        for flight in flights:
            require(flight.get("commit") == args.sha and flight.get("url") == ORIGIN
                    and flight.get("read_only") is True, "flight release mismatch")
            require(isinstance(flight.get("backend"), dict), "backend flight observation missing")
        receipt = build_receipt(args.junit, args.sha, os.environ,
                                before=flights[0].get("backend"), after=flights[1].get("backend"))
        output = Path(args.receipt)
        output.parent.mkdir(parents=True, exist_ok=True)
        # A rerun uses its own attempt and never consumes a prior JUnit artifact.
        with output.open("xb") as stream:
            stream.write(canonical(receipt))
        # These job outputs survive publisher-only retries. Never relabel the tested attempt.
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
                stream.write(f"artifact_name=acceptance-proof-{receipt['run_id']}-{receipt['run_attempt']}\n"
                             f"producer_run_id={receipt['run_id']}\nproducer_run_attempt={receipt['run_attempt']}\n")
    else:
        receipt = json.loads(Path(args.receipt).read_bytes())
        require(receipt["frontend_commit"] == args.sha, "artifact frontend mismatch")
        print(json.dumps(publish(receipt, os.environ, current_main()), indent=2))
