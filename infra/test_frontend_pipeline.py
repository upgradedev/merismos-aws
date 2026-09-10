"""CI-only structural regression checks for main -> deploy -> live UAT."""
import copy
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read_workflow(name):
    # BaseLoader preserves GitHub's 'on' and booleans as strings (YAML 1.1 differs).
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def validate(deploy, uat):
    assert deploy["on"]["push"] == {"branches": ["main"]}
    assert "workflow_dispatch" in deploy["on"]
    assert deploy["concurrency"]["queue"] == "max"
    assert deploy["concurrency"]["cancel-in-progress"] == "false"
    jobs = deploy["jobs"]
    assert jobs["verify"]["uses"] == "./.github/workflows/frontend-ci.yml"
    assert jobs["release"]["needs"] == "verify"
    assert jobs["release"]["if"] == "github.ref == 'refs/heads/main'"
    acceptance = jobs["acceptance"]
    assert acceptance["needs"] == "release"
    assert acceptance["uses"] == "./.github/workflows/aws-uat.yml"
    assert acceptance["with"]["release_sha"] == "${{ github.sha }}"
    # The caller permits OIDC for the separate publisher. Browser jobs narrow it explicitly.
    assert acceptance["permissions"] == {"contents": "read", "actions": "read", "id-token": "write"}
    assert "continue-on-error" not in acceptance
    assert "secrets" not in acceptance
    for trigger in ("workflow_call", "workflow_dispatch"):
        value = uat["on"][trigger]["inputs"]["release_sha"]
        assert value["required"] == "true" and value["type"] == "string"
    assert uat["permissions"] == {"contents": "read"}
    assert uat["concurrency"]["group"] != deploy["concurrency"]["group"]
    assert uat["concurrency"]["queue"] == "max"
    assert uat["concurrency"]["cancel-in-progress"] == "false"
    job = uat["jobs"]["acceptance"]
    assert job["permissions"] == {"contents": "read"}
    assert "continue-on-error" not in job
    assert job["env"]["EXPECTED_RELEASE"] == "${{ inputs.release_sha }}"
    steps = job["steps"]
    indexed = {step.get("id"): step for step in steps if "id" in step}
    assert indexed["journeys"]["run"] == "npm run test:e2e -- --forbid-only"
    assert "continue-on-error" not in indexed["journeys"]
    assert "frontend_smoke.py" in indexed["preflight"]["run"]
    assert "frontend_smoke.py" in indexed["postflight"]["run"]
    assert indexed["postflight"]["if"] == "always() && steps.journeys.outcome != 'skipped'"
    assert steps.index(indexed["preflight"]) < steps.index(indexed["journeys"])
    assert steps.index(indexed["postflight"]) > steps.index(indexed["journeys"])
    assert not any("configure-aws-credentials" in step.get("uses", "") for step in steps)
    assert not any("AWS_" in str(step.get("env", {})) for step in steps)
    artifact = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert artifact["if"] == "always()"
    assert artifact["with"]["retention-days"] == "90"
    for path in ("frontend/test-results/", "frontend/artifacts/browser-junit.xml",
                 "frontend/playwright-report/", "frontend/UAT.testbook.*"):
        assert path in artifact["with"]["path"].splitlines()
    assert "acceptance_receipt.py guard" in indexed["preflight"]["run"]
    compiler = next(step for step in steps if "acceptance_receipt.py create" in step.get("run", ""))
    assert compiler["id"] == "receipt"
    assert job["outputs"] == {key: "${{ steps.receipt.outputs." + key + " }}" for key in ("artifact_name", "producer_run_id", "producer_run_attempt")}
    assert compiler["if"] == "steps.preflight.outcome == 'success' && steps.journeys.outcome == 'success' && steps.postflight.outcome == 'success'"
    assert compiler["env"] == {phase: "${{ steps." + phase.lower() + ".outcome }}" for phase in ("PREFLIGHT", "JOURNEYS", "POSTFLIGHT")}
    transfer = steps[-1]
    assert transfer["with"]["path"] == "acceptance-proof/receipt.json"
    assert transfer["with"]["name"] == "acceptance-proof-${{ github.run_id }}-${{ github.run_attempt }}"
    publisher = uat["jobs"]["publish-proof"]
    assert publisher["needs"] == "acceptance" and publisher["if"] == "github.ref == 'refs/heads/main'"
    assert publisher["permissions"] == {"contents": "read", "actions": "read", "id-token": "write"}
    assert publisher["concurrency"] == jobs["release"]["concurrency"] == {
        "group": "merismos-frontend-publication", "cancel-in-progress": "false", "queue": "max"}
    assert publisher["concurrency"]["group"] != deploy["concurrency"]["group"]
    download = next(step for step in publisher["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"] == {"name": "${{ needs.acceptance.outputs.artifact_name }}", "path": "acceptance-proof"}
    publication = next(step for step in publisher["steps"] if "acceptance_receipt.py publish" in step.get("run", ""))
    for key, value in (("PRODUCER_ARTIFACT", "artifact_name"), ("PRODUCER_RUN_ID", "producer_run_id"), ("PRODUCER_RUN_ATTEMPT", "producer_run_attempt")):
        assert publication["env"][key] == "${{ needs.acceptance.outputs." + value + " }}"
    credentials = next(step for step in publisher["steps"] if "configure-aws-credentials" in step.get("uses", ""))
    assert credentials["with"] == {"role-to-assume": "${{ vars.FRONTEND_RELEASE_ROLE_ARN }}", "aws-region": "eu-west-1"}
    assert not any("npm" in step.get("run", "") or "playwright" in step.get("run", "") for step in publisher["steps"])
    rendered = uat["jobs"]["proof-browser"]
    assert rendered["needs"] == ["acceptance", "publish-proof"]
    assert rendered["env"]["EXPECTED_PROOF_RUN"] == "${{ needs.acceptance.outputs.producer_run_id }}"
    assert rendered["env"]["EXPECTED_PROOF_ATTEMPT"] == "${{ needs.acceptance.outputs.producer_run_attempt }}"
    assert rendered["permissions"] == {"contents": "read"}
    assert not any("configure-aws-credentials" in step.get("uses", "") for step in rendered["steps"])
    assert "AWS_" not in str(job["env"]) and "AWS_" not in str(rendered["env"])
    for candidate in (job, publisher, rendered):
        assert "continue-on-error" not in candidate


class MainAcceptanceContract(unittest.TestCase):
    def setUp(self):
        self.deploy = read_workflow("frontend-deploy.yml")
        self.uat = read_workflow("aws-uat.yml")

    def test_checked_in_pipeline(self):
        validate(self.deploy, self.uat)

    def test_proof_fixtures_are_not_product_acceptance_journeys(self):
        frontend = read_workflow("frontend-ci.yml")
        commands = [step.get("run", "") for step in frontend["jobs"]["verify"]["steps"]]
        self.assertIn("npm run test:proof -- --forbid-only", commands)
        config = (ROOT / "frontend/playwright.proof.config.ts").read_text()
        self.assertIn("testDir: './proof-tests'", config)
        self.assertIn("proof-test-results/proof-junit.xml", config)
        self.assertNotIn("e2e.xml", config.split("reporter:", 1)[1])
        normal = (ROOT / "frontend/playwright.config.ts").read_text()
        self.assertIn("testDir: './e2e'", normal)
        self.assertIn("test-results/e2e.xml", normal)
        commands = [step.get("run", "") for step in self.uat["jobs"]["proof-browser"]["steps"]]
        self.assertIn("npm run test:proof -- public-proof.spec.ts --forbid-only", commands)

    def test_missing_main_trigger_is_rejected(self):
        self.deploy["on"]["push"]["branches"] = ["dev"]
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_test_before_deployment_is_rejected(self):
        self.deploy["jobs"]["acceptance"]["needs"] = "verify"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_dropped_pending_merges_are_rejected(self):
        self.deploy["concurrency"]["queue"] = "single"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_wrong_tested_commit_is_rejected(self):
        self.deploy["jobs"]["acceptance"]["with"]["release_sha"] = "main"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_ignored_browser_failure_is_rejected(self):
        self.deploy["jobs"]["acceptance"]["continue-on-error"] = "true"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_cloud_credentials_in_browser_job_are_rejected(self):
        self.uat["permissions"]["id-token"] = "write"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_browser_job_cannot_inherit_publisher_credentials(self):
        for name in ("acceptance", "proof-browser"):
            for breakage in ("oidc", "credentials", "environment"):
                uat = copy.deepcopy(self.uat)
                job = uat["jobs"][name]
                if breakage == "oidc":
                    job["permissions"]["id-token"] = "write"
                elif breakage == "credentials":
                    job["steps"].append({"uses": "aws-actions/configure-aws-credentials@v4"})
                else:
                    job["env"]["AWS_ACCESS_KEY_ID"] = "unacceptable"
                with self.subTest(name=name, breakage=breakage), self.assertRaises(AssertionError):
                    validate(self.deploy, uat)

    def test_early_unlocked_or_cross_run_publication_is_rejected(self):
        for breakage in ("early", "branch", "lock", "artifact", "role", "browser"):
            uat = copy.deepcopy(self.uat)
            job = uat["jobs"]["publish-proof"]
            if breakage == "early":
                job["needs"] = "verify"
            elif breakage == "branch":
                job["if"] = "always()"
            elif breakage == "lock":
                job["concurrency"]["group"] = "unlocked"
            elif breakage == "artifact":
                next(s for s in job["steps"] if "download-artifact" in s.get("uses", ""))["with"]["name"] = "prior-receipt"
            elif breakage == "role":
                next(s for s in job["steps"] if "configure-aws" in s.get("uses", ""))["with"]["role-to-assume"] = "backend-role"
            else:
                job["steps"].append({"run": "npx playwright test"})
            with self.subTest(breakage=breakage), self.assertRaises(AssertionError):
                validate(self.deploy, uat)

    def test_publisher_retry_cannot_relabel_producer_identity(self):
        uat = copy.deepcopy(self.uat)
        job = uat["jobs"]["publish-proof"]
        step = next(step for step in job["steps"] if "acceptance_receipt.py publish" in step.get("run", ""))
        step["env"]["PRODUCER_RUN_ATTEMPT"] = "${{ github.run_attempt }}"
        with self.assertRaises(AssertionError):
            validate(self.deploy, uat)

    def test_missing_postflight_or_failure_artifacts_are_rejected(self):
        for broken in ("postflight", "artifact"):
            uat = copy.deepcopy(self.uat)
            for step in uat["jobs"]["acceptance"]["steps"]:
                if broken == "postflight" and step.get("id") == "postflight":
                    step["run"] = "true"
                if broken == "artifact" and step.get("uses", "").startswith("actions/upload-artifact@"):
                    step["if"] = "success()"
            with self.subTest(broken=broken), self.assertRaises(AssertionError):
                validate(self.deploy, uat)


if __name__ == "__main__":
    unittest.main(verbosity=2)
