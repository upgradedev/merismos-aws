"""Dependency-free regression tests for the deployment boundary."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


stack = module("frontend_stack")
publisher = module("frontend_publish")
smoke = module("frontend_smoke")
COMMIT = "1" * 40


class HostingContract(unittest.TestCase):
    def test_each_product_has_private_retained_bucket_and_oac(self):
        for product in ("lasttake", "merismos", "archon"):
            resources = stack.template(product, "upgradedev/" + product)["Resources"]
            bucket = resources["Site"]
            self.assertEqual(bucket["DeletionPolicy"], "Retain")
            self.assertTrue(all(bucket["Properties"]["PublicAccessBlockConfiguration"].values()))
            self.assertNotIn("WebsiteConfiguration", bucket["Properties"])
            self.assertEqual(resources["Access"]["Properties"]["OriginAccessControlConfig"]["SigningBehavior"], "always")
            grants = resources["SitePolicy"]["Properties"]["PolicyDocument"]["Statement"]
            allow = next(item for item in grants if item["Effect"] == "Allow")
            self.assertEqual(allow["Principal"], {"Service": "cloudfront.amazonaws.com"})
            self.assertIn("AWS:SourceArn", allow["Condition"]["StringEquals"])

    def test_api_never_cached_or_error_mapped_to_html(self):
        config = stack.template("archon", "upgradedev/archon-aws-strands")["Resources"]["Distribution"]["Properties"]["DistributionConfig"]
        self.assertNotIn("CustomErrorResponses", config)
        for behavior in config["CacheBehaviors"]:
            if behavior["TargetOriginId"] == "api":
                self.assertEqual(behavior["CachePolicyId"], stack.DISABLED)
                self.assertEqual(behavior["OriginRequestPolicyId"], stack.EXCEPT_HOST)
                self.assertNotIn("FunctionAssociations", behavior)
        origin = next(item for item in config["Origins"] if item["Id"] == "api")
        self.assertEqual(origin["CustomOriginConfig"]["OriginProtocolPolicy"], "https-only")

    def test_main_only_identity_cannot_mutate_other_stacks(self):
        resources = stack.template("lasttake", "upgradedev/lasttake-aws")["Resources"]
        role = resources["ReleaseRole"]["Properties"]
        trust = role["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"]
        self.assertEqual(trust["token.actions.githubusercontent.com:sub"], {"Fn::Sub": "${GitHubSubjectPrefix}:ref:refs/heads/main"})
        grants = role["Policies"][0]["PolicyDocument"]["Statement"]
        actions = [action for grant in grants for action in ([grant["Action"]] if isinstance(grant["Action"], str) else grant["Action"])]
        self.assertFalse(any("Delete" in action or "iam:" in action or "UpdateStack" in action for action in actions))

    def test_router_executes_actual_javascript(self):
        checks = """
const cases = [
 ['/', 'GET', '/index.html'], ['/offers', 'GET', '/index.html'],
 ['/offers/offer-42', 'GET', '/index.html'], ['/actions', 'HEAD', '/index.html'],
 ['/api/state', 'GET', '/api/state'], ['/api', 'GET', '/api'],
 ['/assets/missing.js', 'GET', '/assets/missing.js'],
 ['/receipts/example.json', 'GET', '/receipts/example.json'],
 ['/UAT.testbook.html', 'GET', '/UAT.testbook.html'],
 ['/offers', 'POST', '/offers'], ['/not-a-route', 'GET', '/not-a-route']
];
for (const [uri, method, expected] of cases) {
 const out = handler({request: {uri, method}});
 if (out.uri !== expected) throw new Error(uri + ' became ' + out.uri);
}
"""
        subprocess.run(["node", "-e", stack.SPA_CODE + checks], check=True)

    def test_invalid_product_repository_refused(self):
        for product, repo in [("customer", "upgradedev/test"), ("lasttake", "upgradedev/test:ref:x")]:
            with self.assertRaises(ValueError):
                stack.template(product, repo)


class PublishContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dist = Path(self.temp.name)
        (self.dist / "assets").mkdir()
        (self.dist / "assets/app-123.js").write_text("export const ready = true;", encoding="utf-8")
        (self.dist / "index.html").write_text('<html><head><script type="module" src="/assets/app-123.js"></script></head><body></body></html>', encoding="utf-8")

    def test_release_validates_assets_and_pins_commit(self):
        payloads = publisher.build_release(self.dist, COMMIT)
        manifest = json.loads(payloads["release.json"])
        self.assertEqual(manifest["commit"], COMMIT)
        self.assertIn('content="' + COMMIT + '"', payloads["index.html"].decode())
        self.assertEqual(len(manifest["files"]["assets/app-123.js"]), 64)
        # Re-publishing a downloaded archive must not duplicate provenance.
        for key, value in payloads.items():
            (self.dist / key).write_bytes(value)
        self.assertEqual(payloads, publisher.build_release(self.dist, COMMIT))

    def test_missing_asset_bad_sha_and_secret_fail_closed(self):
        with self.assertRaises(ValueError):
            publisher.build_release(self.dist, "main")
        (self.dist / "assets/app-123.js").unlink()
        with self.assertRaises(ValueError):
            publisher.build_release(self.dist, COMMIT)
        (self.dist / "assets/app-123.js").write_text("-----BEGIN PRIVATE KEY-----")
        with self.assertRaises(ValueError):
            publisher.build_release(self.dist, COMMIT)

    def test_hidden_files_and_unexpected_artifacts_refused(self):
        for name in (".env", "settings.exe"):
            path = self.dist / name
            path.write_text("unshippable")
            with self.assertRaises(ValueError):
                publisher.build_release(self.dist, COMMIT)
            path.unlink()

    def test_index_is_last_and_only_exact_stack_bucket_is_written(self):
        calls = []
        def command(*args):
            calls.append(args)
            if args[:2] == ("cloudformation", "describe-stacks"):
                return {"Stacks": [{"Outputs": [
                    {"OutputKey": "FrontendBucket", "OutputValue": "lasttake-web-308857099262-eu-west-1"},
                    {"OutputKey": "DistributionId", "OutputValue": "EXAMPLE"},
                    {"OutputKey": "FrontendUrl", "OutputValue": "https://example.cloudfront.net/"},
                ]}]}
            return {}
        result = publisher.publish(self.dist, COMMIT, "lasttake-frontend", "eu-west-1", command)
        writes = [args for args in calls if args[:2] == ("s3api", "put-object")]
        self.assertEqual(writes[-1][writes[-1].index("--key") + 1], "index.html")
        self.assertTrue(all("lasttake-web-308857099262-eu-west-1" in args for args in writes))
        self.assertFalse(any("delete" in " ".join(args).lower() for args in calls))
        for args in writes:
            key = args[args.index("--key") + 1]
            cache = args[args.index("--cache-control") + 1]
            if key.endswith(".html"):
                self.assertIn("no-store", cache)
        self.assertEqual(result["commit"], COMMIT)


class LiveGateContract(unittest.TestCase):
    def request(self, url):
        if url.endswith("release.json"):
            return 200, {}, json.dumps({"commit": COMMIT}).encode()
        if "definitely-not" in url:
            return 404, {}, b"missing"
        if url.endswith(".js"):
            return 200, {}, b"export{}"
        return 200, {"Content-Security-Policy": "default-src 'self'", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"}, (
            '<html><head><meta name="application-commit" content="' + COMMIT + '"><script src="/assets/a.js"></script></head></html>'
        ).encode()

    def test_gate_passes_expected_read_only_flow(self):
        self.assertTrue(smoke.check("https://example.invalid", COMMIT, self.request)["read_only"])

    def test_gate_proves_non200_and_spa_api_fail(self):
        with self.assertRaises(AssertionError):
            smoke.check("https://example.invalid", COMMIT, lambda url: (503, {}, b"down"))
        def fail_open(url):
            if "api/definitely" in url:
                return 200, {}, b"index.html"
            return self.request(url)
        with self.assertRaises(AssertionError):
            smoke.check("https://example.invalid", COMMIT, fail_open)
        with self.assertRaises(AssertionError):
            smoke.check("https://example.invalid", "2" * 40, self.request)


if __name__ == "__main__":
    unittest.main(verbosity=2)
