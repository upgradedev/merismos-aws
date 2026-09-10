"""CI-only unit and CLI-functional negative controls; every AWS call is a fake."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import acceptance_receipt as proof
from frontend_publish import build_release

COMMIT = "1" * 40
OTHER = "2" * 40
NOW = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)
ENV = {"GITHUB_REPOSITORY": proof.REPOSITORY, "GITHUB_REF": "refs/heads/main",
       "GITHUB_SHA": COMMIT, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
       "PREFLIGHT": "success", "JOURNEYS": "success", "POSTFLIGHT": "success"}
XML = ('<testsuites tests="2" failures="0" skipped="0" errors="0">'
       '<testsuite name="desktop" tests="1"><testcase name="synthetic case A"><system-out>do not publish raw output</system-out></testcase></testsuite>'
       '<testsuite name="mobile" tests="1"><testcase name="synthetic case B"/></testsuite></testsuites>')


class ReceiptContract(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.junit = self.root / "e2e.xml"
        self.junit.write_text(XML)
        self.receipt = proof.build_receipt(self.junit, COMMIT, ENV, NOW)
        self.objects = {"release.json": json.dumps({"commit": COMMIT}).encode()}
        self.calls = []
        self.origin_sha = COMMIT
        self.change_after_immutable = False

    def command(self, *args):
        self.calls.append(args)
        if args[:2] == ("cloudformation", "describe-stacks"):
            return {"Stacks": [{"Outputs": [
                {"OutputKey": "FrontendBucket", "OutputValue": "merismos-web-123456789012-eu-west-1"},
                {"OutputKey": "FrontendUrl", "OutputValue": proof.ORIGIN}]}]}
        key = args[args.index("--key") + 1]
        if args[:2] == ("s3api", "get-object"):
            Path(args[args.index("--key") + 2]).write_bytes(self.objects[key])
            return {}
        self.assertEqual(args[:2], ("s3api", "put-object"))
        self.assertIn("merismos-web-123456789012-eu-west-1", args)
        if "--if-none-match" in args and key in self.objects:
            raise subprocess.CalledProcessError(1, args, stderr="PreconditionFailed")
        self.objects[key] = Path(args[args.index("--body") + 1]).read_bytes()
        if self.change_after_immutable and key.startswith("acceptance/runs/"):
            self.objects["release.json"] = json.dumps({"commit": OTHER}).encode()
        return {}

    def request(self, url):
        self.assertEqual(url, proof.ORIGIN + "release.json")
        return 200, {}, json.dumps({"commit": self.origin_sha}).encode()

    def publish(self, receipt=None, env=None, main=COMMIT):
        return proof.publish(receipt or self.receipt, env or ENV, main, self.command, self.request, NOW)

    def test_real_cases_derive_counts_and_raw_scenarios_never_leave_compiler(self):
        self.assertEqual(self.receipt["junit"], {"total": 2, "passed": 2, "failed": 0, "skipped": 0})
        self.assertEqual(self.receipt["backend_commit"], "unavailable")
        self.assertEqual(self.receipt["workflow_status"], "NOT_ASSERTED")
        data = proof.canonical(self.receipt)
        for private in (b"synthetic case", b"do not publish raw output", b"system-out"):
            self.assertNotIn(private, data)

    def test_failure_skips_empty_malformed_and_disagreeing_junit_refuse_receipt(self):
        for xml in ("", "<broken", "<testsuites/>", "<html/>", XML.replace('tests="2"', 'tests="999"'),
                    XML.replace('<testcase name="synthetic case B"/>', '<testcase><failure/></testcase>'),
                    XML.replace('<testcase name="synthetic case B"/>', '<testcase><error/></testcase>'),
                    XML.replace('<testcase name="synthetic case B"/>', '<testcase><skipped/></testcase>'),
                    '<!DOCTYPE testsuite><testsuite><testcase/></testsuite>'):
            self.junit.write_text(xml)
            with self.subTest(xml=xml), self.assertRaises((ValueError, proof.ElementTree.ParseError)):
                proof.build_receipt(self.junit, COMMIT, ENV, NOW)

    def test_every_phase_must_really_succeed(self):
        for phase in ("PREFLIGHT", "JOURNEYS", "POSTFLIGHT"):
            for status in ("", "skipped", "cancelled", "failure"):
                with self.subTest(phase=phase, status=status), self.assertRaises(ValueError):
                    proof.build_receipt(self.junit, COMMIT, {**ENV, phase: status}, NOW)

    def test_same_testcase_in_different_projects_counts_but_duplicate_in_same_project_refuses(self):
        for project_field in ("name", "hostname"):
            self.junit.write_text(f'<testsuites><testsuite {project_field}="desktop"><testcase classname="journey" name="same"/></testsuite>'
                                 f'<testsuite {project_field}="mobile"><testcase classname="journey" name="same"/></testsuite></testsuites>')
            self.assertEqual(proof.junit_counts(self.junit)["passed"], 2)
        self.junit.write_text('<testsuite name="desktop"><testcase name="same"/><testcase name="same"/></testsuite>')
        with self.assertRaisesRegex(ValueError, "duplicate"):
            proof.junit_counts(self.junit)

    def test_malformed_or_unsanitized_receipts_cannot_be_published(self):
        changes = [{"schema_version": True}, {"application": "another"}, {"environment": "offline"},
                   {"frontend_commit": "main"}, {"backend_commit": COMMIT}, {"backend_basis": "same as frontend"},
                   {"run_id": "../../other"}, {"run_attempt": 2}, {"run_url": "https://example.invalid"},
                   {"human_uat": "PASS"}, {"mode": "real_food_rescue"}, {"limits": "none"},
                   {"workflow_status": "SUCCESS"}, {"token": "forbidden field"},
                   {"junit": {"total": 2, "passed": True, "failed": 0, "skipped": 0}},
                   {"observed_at": "2026-09-09T05:59:59Z"}, {"observed_at": "2026-09-10T06:00:01Z"}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.publish({**self.receipt, **change})
        self.assertEqual(self.calls, [])

    def test_stale_dispatch_other_ref_repo_or_run_attempt_refused(self):
        for change in ({"GITHUB_SHA": OTHER}, {"GITHUB_REF": "refs/heads/codex/test"},
                       {"GITHUB_REPOSITORY": "upgradedev/other"}, {"GITHUB_RUN_ID": "122"},
                       {"GITHUB_RUN_ATTEMPT": "1"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.publish(env={**ENV, **change})
        with self.assertRaises(ValueError):
            self.publish(main=OTHER)
        self.assertEqual(self.calls, [])

    def test_immutable_then_latest_no_delete_and_exact_retry_is_identical(self):
        result = self.publish()
        immutable = "acceptance/runs/123-2.json"
        self.assertEqual(result["receipt_url"], proof.ORIGIN + immutable)
        self.assertEqual(self.objects[immutable], self.objects["acceptance.json"])
        puts = [call for call in self.calls if call[:2] == ("s3api", "put-object")]
        self.assertEqual([call[call.index("--key") + 1] for call in puts], [immutable, "acceptance.json"])
        self.assertIn("--if-none-match", puts[0])
        self.assertIn("no-store,max-age=0", puts[-1])
        self.assertNotIn("delete", str(self.calls).lower())
        self.publish()

    def test_conflicting_immutable_bytes_do_not_replace_history_or_latest(self):
        self.objects["acceptance/runs/123-2.json"] = b"old immutable bytes"
        self.objects["acceptance.json"] = b"previous latest"
        with self.assertRaisesRegex(ValueError, "different bytes"):
            self.publish()
        self.assertEqual(self.objects["acceptance/runs/123-2.json"], b"old immutable bytes")
        self.assertEqual(self.objects["acceptance.json"], b"previous latest")

    def test_access_denial_is_not_treated_as_an_identical_retry(self):
        def deny(*args):
            if args[:2] == ("s3api", "put-object"):
                raise subprocess.CalledProcessError(1, args, stderr="AccessDenied")
            return self.command(*args)
        with self.assertRaises(subprocess.CalledProcessError):
            proof.publish(self.receipt, ENV, COMMIT, deny, self.request, NOW)
        self.assertNotIn("acceptance.json", self.objects)

    def test_mismatch_at_origin_or_cdn_and_mid_publication_race_refuse_latest(self):
        for point in ("origin", "cdn", "after-immutable"):
            self.objects = {"release.json": json.dumps({"commit": OTHER if point == "origin" else COMMIT}).encode()}
            self.origin_sha = OTHER if point == "cdn" else COMMIT
            self.change_after_immutable = point == "after-immutable"
            with self.subTest(point=point), self.assertRaises(ValueError):
                self.publish()
            self.assertNotIn("acceptance.json", self.objects)

    def test_unexpected_stack_bucket_or_origin_refused(self):
        for field, value in (("FrontendBucket", "another-bucket"), ("FrontendUrl", "https://example.invalid/")):
            def wrong(*args):
                result = self.command(*args)
                for item in result["Stacks"][0]["Outputs"]:
                    if item["OutputKey"] == field:
                        item["OutputValue"] = value
                return result
            with self.subTest(field=field), self.assertRaises(ValueError):
                proof.publish(self.receipt, ENV, COMMIT, wrong, self.request, NOW)

    def test_frontend_release_refuses_to_ship_or_overwrite_acceptance_receipts(self):
        dist = self.root / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text('<head><script src="/assets/app.js"></script></head>')
        (dist / "assets/app.js").write_text("export{}")
        for key in ("acceptance.json", "acceptance/runs/old.json"):
            path = dist / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "post-acceptance publisher"):
                build_release(dist, COMMIT)
            path.unlink()

    def test_cli_writes_only_aggregate_and_refuses_existing_output_and_missing_junit(self):
        output = self.root / "receipt.json"
        command = [sys.executable, str(Path(proof.__file__)), "create", "--sha", COMMIT,
                   "--junit", str(self.junit), "--receipt", str(output)]
        result = subprocess.run(command, env={**os.environ, **ENV}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(output.read_bytes())), proof.FIELDS)
        self.assertNotIn("synthetic case", output.read_text())
        self.assertNotEqual(subprocess.run(command, env={**os.environ, **ENV}, capture_output=True).returncode, 0)
        self.junit.unlink()
        self.assertNotEqual(subprocess.run(command, env={**os.environ, **ENV}, capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
