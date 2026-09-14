"""CI-only unit and CLI-functional negative controls; every AWS call is a fake."""
import json
import os
import re
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
       "PRODUCER_RUN_ID": "123", "PRODUCER_RUN_ATTEMPT": "2", "PRODUCER_ARTIFACT": "acceptance-proof-123-2",
       "PREFLIGHT": "success", "JOURNEYS": "success", "POSTFLIGHT": "success"}
CASES = ''.join(f'<testcase classname="journey" name="synthetic case {i}"><system-out>do not publish raw output</system-out></testcase>' for i in range(12))
XML = ('<testsuites tests="24" failures="0" skipped="0" errors="0">'
       f'<testsuite name="desktop" tests="12">{CASES}</testsuite>'
       f'<testsuite name="mobile" tests="12">{CASES}</testsuite></testsuites>')


def html(sha=COMMIT):
    return f'<html><head><meta name="application-commit" content="{sha}"></head></html>'.encode()


class ReceiptContract(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.junit = self.root / "e2e.xml"
        self.junit.write_text(XML)
        self.receipt = proof.build_receipt(self.junit, COMMIT, ENV, NOW)
        self.objects = {"release.json": json.dumps({"commit": COMMIT}).encode(), "index.html": html()}
        self.calls = []
        self.origin_sha = COMMIT
        self.html_sha = COMMIT
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
        if url == proof.ORIGIN:
            return 200, {}, html(self.html_sha)
        self.assertEqual(url, proof.ORIGIN + "release.json")
        return 200, {}, json.dumps({"commit": self.origin_sha}).encode()

    def publish(self, receipt=None, env=None, main=COMMIT):
        return proof.publish(receipt or self.receipt, env or ENV, main, self.command, self.request, NOW)

    def test_real_cases_derive_counts_and_raw_scenarios_never_leave_compiler(self):
        self.assertEqual(self.receipt["junit"], {"total": 24, "passed": 24, "failed": 0, "skipped": 0})
        self.assertEqual(self.receipt["backend_commit"], "unavailable")
        self.assertEqual(self.receipt["workflow_status"], "NOT_ASSERTED")
        data = proof.canonical(self.receipt)
        for private in (b"synthetic case", b"do not publish raw output", b"system-out"):
            self.assertNotIn(private, data)

    def test_publisher_and_public_verifier_share_the_exact_limits_contract(self):
        verifier = (Path(__file__).parents[1] / "frontend" / "public" / "acceptance.js").read_text()
        match = re.search(r"^export const LIMITS = '([^']*)';$", verifier, re.MULTILINE)
        self.assertIsNotNone(match, "public verifier must export one literal LIMITS contract")
        self.assertEqual(match.group(1), proof.LIMITS)

    def test_observed_backend_may_differ_from_frontend_without_inventing_parity(self):
        known = {"commit": OTHER, "status": "known", "source": "ci_package"}
        receipt = proof.build_receipt(self.junit, COMMIT, ENV, NOW, known, known)
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["backend_commit"], OTHER)
        self.assertEqual(receipt["backend_basis"], proof.KNOWN_BACKEND_BASIS)
        self.assertEqual(receipt["frontend_commit"], COMMIT)
        self.assertEqual(proof.validate(receipt, NOW), receipt)
        for after in (proof.UNKNOWN, {**known, "commit": COMMIT}, {**known, "commit": "fake"}):
            with self.subTest(after=after), self.assertRaises(ValueError):
                proof.build_receipt(self.junit, COMMIT, ENV, NOW, known, after)

    def test_legacy_unknown_receipts_remain_valid_without_rewriting_their_basis(self):
        legacy = {**self.receipt, "schema_version": 1, "backend_basis": proof.BACKEND_BASIS}
        self.assertEqual(proof.validate(legacy, NOW), legacy)
        with self.assertRaises(ValueError):
            proof.validate({**legacy, "backend_commit": COMMIT}, NOW)

    def test_known_backend_rechecked_before_each_public_write_and_failure_retains_history(self):
        known = {"commit": OTHER, "status": "known", "source": "ci_package"}
        receipt = proof.build_receipt(self.junit, COMMIT, ENV, NOW, known, known)
        calls = []
        def version_request(url):
            calls.append(url)
            return 200, {"content-type": "application/json"}, json.dumps({
                "schema_version": 1, "application": "merismos", **known}).encode()
        proof.publish(receipt, ENV, COMMIT, self.command, self.request, NOW, version_request)
        self.assertEqual(calls, [proof.ORIGIN + "api/version"] * 2)
        self.assertEqual(json.loads(self.objects["acceptance.json"])["backend_commit"], OTHER)
        self.objects.pop("acceptance/runs/123-2.json")
        self.objects["acceptance.json"] = b"previous latest"
        calls.clear()
        def changed(url):
            status, headers, body = version_request(url)
            if len(calls) > 1:
                body = body.replace(OTHER.encode(), COMMIT.encode())
            return status, headers, body
        with self.assertRaisesRegex(ValueError, "backend changed"):
            proof.publish(receipt, ENV, COMMIT, self.command, self.request, NOW, changed)
        self.assertIn("acceptance/runs/123-2.json", self.objects)
        self.assertEqual(self.objects["acceptance.json"], b"previous latest")

    def test_failure_skips_empty_malformed_and_disagreeing_junit_refuse_receipt(self):
        for xml in ("", "<broken", "<testsuites/>", "<html/>", XML.replace('tests="24"', 'tests="999"'),
                    XML.replace('</testcase>', '<failure/></testcase>', 1),
                    XML.replace('</testcase>', '<error/></testcase>', 1),
                    XML.replace('</testcase>', '<skipped/></testcase>', 1),
                    '<!DOCTYPE testsuite><testsuite><testcase/></testsuite>'):
            self.junit.write_text(xml)
            with self.subTest(xml=xml), self.assertRaises((ValueError, proof.ElementTree.ParseError)):
                proof.build_receipt(self.junit, COMMIT, ENV, NOW)

    def test_independent_23_case_fixture_cannot_create_or_publish_proof(self):
        self.junit.write_text('<testsuite tests="23">' + ''.join(f'<testcase name="independent-{i}"/>' for i in range(23)) + '</testsuite>')
        with self.assertRaisesRegex(ValueError, "below 24"):
            proof.build_receipt(self.junit, COMMIT, ENV, NOW)
        smaller = {**self.receipt, "junit": {"total": 23, "passed": 23, "failed": 0, "skipped": 0}}
        with self.assertRaisesRegex(ValueError, "below 24"):
            self.publish(smaller)
        self.assertEqual(self.calls, [])

    def test_retry_and_flaky_tags_are_refused_even_with_clean_aggregate_counters(self):
        for tag in ("flakyFailure", "flakyError", "rerunFailure", "rerunError", "retry"):
            self.junit.write_text(XML.replace('</testcase>', f'<{tag}>earlier failed attempt</{tag}></testcase>', 1))
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, "retry or flaky"):
                proof.build_receipt(self.junit, COMMIT, ENV, NOW)
        for attribute in ('retries="1"', 'flaky="true"', 'status="flaky"'):
            self.junit.write_text(XML.replace('<testcase ', f'<testcase {attribute} ', 1))
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
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

    def test_publisher_only_retry_preserves_the_producer_attempt(self):
        self.publish()
        original = self.objects["acceptance/runs/123-2.json"]
        result = self.publish(env={**ENV, "GITHUB_RUN_ATTEMPT": "3"})
        self.assertEqual(result["receipt_url"], proof.ORIGIN + "acceptance/runs/123-2.json")
        self.assertEqual(self.objects["acceptance.json"], original)
        self.assertNotIn("acceptance/runs/123-3.json", self.objects)
        for change in ({"PRODUCER_RUN_ID": "124"}, {"PRODUCER_RUN_ATTEMPT": "3"},
                       {"PRODUCER_ARTIFACT": "acceptance-proof-123-3"}, {"PRODUCER_RUN_ATTEMPT": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.publish(env={**ENV, "GITHUB_RUN_ATTEMPT": "3", **change})

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
            self.objects = {"release.json": json.dumps({"commit": OTHER if point == "origin" else COMMIT}).encode(), "index.html": html()}
            self.origin_sha = OTHER if point == "cdn" else COMMIT
            self.change_after_immutable = point == "after-immutable"
            with self.subTest(point=point), self.assertRaises(ValueError):
                self.publish()
            self.assertNotIn("acceptance.json", self.objects)

    def test_manifest_alone_cannot_accept_wrong_missing_or_changed_root_html(self):
        self.html_sha = OTHER
        with self.assertRaisesRegex(ValueError, "served root HTML mismatch"):
            self.publish()
        self.html_sha = COMMIT
        for body in (html(OTHER), b"<html>missing marker</html>", html() + html()):
            self.objects["index.html"] = body
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.publish()
        self.objects["index.html"] = html()
        reads = 0
        def changed(url):
            nonlocal reads
            if url == proof.ORIGIN:
                reads += 1
                return 200, {}, html(OTHER if reads > 1 else COMMIT)
            return self.request(url)
        with self.assertRaisesRegex(ValueError, "served root HTML mismatch"):
            proof.publish(self.receipt, ENV, COMMIT, self.command, changed, NOW)
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
        outputs = self.root / "outputs.txt"
        cli_env = {**os.environ, **ENV, "GITHUB_OUTPUT": str(outputs)}
        command = [sys.executable, str(Path(proof.__file__)), "create", "--sha", COMMIT,
                   "--junit", str(self.junit), "--receipt", str(output)]
        flight = self.root / "flight.json"
        flight.write_text(json.dumps({"commit": COMMIT, "url": proof.ORIGIN, "read_only": True,
                                     "backend": proof.UNKNOWN}))
        command += ["--preflight", str(flight), "--postflight", str(flight)]
        missing = self.root / "missing-flight.json"
        missing.write_text(json.dumps({"commit": COMMIT, "url": proof.ORIGIN, "read_only": True}))
        invalid = [*command[:-4], "--preflight", str(missing), "--postflight", str(flight)]
        self.assertNotEqual(subprocess.run(invalid, env=cli_env, capture_output=True).returncode, 0)
        self.assertFalse(output.exists())
        result = subprocess.run(command, env=cli_env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(output.read_bytes())), proof.FIELDS)
        self.assertNotIn("synthetic case", output.read_text())
        self.assertIn("artifact_name=acceptance-proof-123-2", outputs.read_text())
        self.assertIn("producer_run_attempt=2", outputs.read_text())
        self.assertNotEqual(subprocess.run(command, env=cli_env, capture_output=True).returncode, 0)
        self.junit.unlink()
        self.assertNotEqual(subprocess.run(command, env=cli_env, capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
