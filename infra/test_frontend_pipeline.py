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
    assert acceptance["permissions"] == {"contents": "read"}
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
    artifact = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert artifact["if"] == "always()"
    assert artifact["with"]["retention-days"] == "14"
    for path in ("frontend/test-results/", "frontend/artifacts/browser-junit.xml",
                 "frontend/playwright-report/", "frontend/UAT.testbook.*"):
        assert path in artifact["with"]["path"].splitlines()


class MainAcceptanceContract(unittest.TestCase):
    def setUp(self):
        self.deploy = read_workflow("frontend-deploy.yml")
        self.uat = read_workflow("aws-uat.yml")

    def test_checked_in_pipeline(self):
        validate(self.deploy, self.uat)

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
