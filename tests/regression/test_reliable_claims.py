"""Small claim-drift checks on current prose and load-bearing release wiring."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIVE = "https://d2qnkmlhs7y5fp.cloudfront.net/"


@pytest.mark.parametrize("path", [
    "README.md", "docs/devpost-description.md", "docs/video-script.md",
    "docs/the-screenshots-to-submit.md", "docs/architecture.md",
    "docs/deploy-2026-09-02.md", "docs/live-run-2026-09-02.md",
])
def test_first_screen_names_persona_live_path_and_real_demo_limit(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    assert LIVE in text[:1000]
    assert "coordinator" in text[:1000].lower()
    assert "Try success" in text[:1400]
    assert "Strands" in text
    assert "read-only" in text
    assert "no model network call" in text.replace("\n", " ")
    assert "licen" in text.lower()


def test_narration_and_script_share_bounds_and_do_not_claim_automatic_delivery():
    data = json.loads((ROOT / "video/narration.json").read_text(encoding="utf-8"))
    assert data["schemaVersion"] == "merismos.submission-video/v1"
    assert "voice" not in data
    assert [entry["id"] for entry in data["segments"]] == [
        "hook", "surface", "trigger", "live", "sponsor", "evidence", "close"]
    text = " ".join(entry["captionText"] for entry in data["segments"])
    assert "no model network call" in text
    assert "time" in text and "unmeasured" in text
    assert "nothing is sent automatically" in text
    assert "Every refusal" not in text
    assert "90–174" in (ROOT / "docs/video-script.md").read_text(encoding="utf-8")


def test_full_history_and_fixed_archive_are_not_silently_narrowed():
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in ci and "--log-opts=--all" in ci
    assert "--log-opts=-1" not in ci
    archive = (ROOT / ".github/workflows/frontend-ci.yml").read_text(encoding="utf-8")
    for literal in ("34360378251", "10107806322", "sha256", "retention-days: 90",
                    "workflow_dispatch", "actions: read"):
        assert literal in archive
    assert "extractall" not in archive


def test_secret_scan_exception_is_only_the_reviewed_immutable_synthetic_fixture():
    ignored = {line.strip() for line in (ROOT / ".gitleaksignore").read_text().splitlines()
               if line.strip() and not line.lstrip().startswith("#")}
    exact = "9d5d7d8d53b35d6bc07da6272de42f71126cbb47:tests/conftest.py:aws-access-token:63"
    assert ignored == {exact}
    # A different key/line or commit in the same file and rule must still be scanned.
    assert exact.replace(":63", ":64") not in ignored
    assert exact.replace("9d5d7d8d53b35d6bc07da6272de42f71126cbb47", "a" * 40) not in ignored
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "--log-opts=--all" in ci
    assert "--baseline-path" not in ci and "--exit-code=0" not in ci


def test_live_model_proof_uses_private_iam_not_fake_http_authority():
    deploy = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    assert 'default: "eu.anthropic.claude-opus-5"' in deploy
    assert "--function-name merismos-runner --invocation-type Event" in deploy
    assert "source:\"merismos.background\"" in deploy
    assert "/publication-capabilities" in deploy
    assert '.checks.corpus_freshness_read.allowed == true' in deploy
    assert '.checks.custody_head_read.allowed == true' in deploy
    assert '"authorizer":' not in deploy
    assert '"principalId":' not in deploy


def _flat(path):
    return " ".join((ROOT / path).read_text(encoding="utf-8").split())


def test_current_public_surfaces_keep_rules_before_eligible_strands_loops():
    rules_first = [
        "README.md", "docs/devpost-description.md", "docs/architecture.md",
        "docs/video-script.md", "frontend/src/ArchitectureView.tsx",
        "frontend/src/UserJourneysView.tsx", "video/narration.json",
    ]
    for path in rules_first:
        text = _flat(path).lower()
        assert ("rules first" in text or "deterministic rules run first" in text
                or "deterministic rules before" in text), path
    for path in (
        "README.md", "docs/devpost-description.md", "docs/video-script.md",
        "frontend/src/ArchitectureView.tsx", "frontend/src/UserJourneysView.tsx",
        "video/narration.json",
    ):
        text = _flat(path).lower()
        assert "fixed" in text and "tool sequence" in text and "closing answer" in text, path


def test_current_surfaces_scope_mutability_collection_and_source_references():
    architecture = _flat("frontend/src/ArchitectureView.tsx")
    journeys = _flat("frontend/src/UserJourneysView.tsx")
    pickups = _flat("frontend/src/Pickups.tsx")
    assert "separate versioned workspace item" in architecture
    assert "not an append-only ledger" in architecture
    assert "not pickup events in the append-only run ledger" in journeys
    assert "agreed time is optional" in journeys
    assert "Optional. If you set one" in pickups
    for path in ("README.md", "docs/devpost-description.md", "docs/architecture.md",
                 "docs/evidence.md", "video/narration.json"):
        assert "logical source references from the current API snapshot" in _flat(path), path


def test_me18_and_capture_preflight_remain_precisely_scoped():
    for path in ("README.md", "docs/evidence.md", "frontend/UAT.testbook.html",
                 "frontend/public/acceptance.html", "frontend/public/acceptance.js"):
        text = _flat(path)
        assert "writer read-capability probe" in text, path
        assert "publication and recovery drill (ME18)" not in text, path
    testbook = json.loads((ROOT / "frontend/UAT.testbook.json").read_text(encoding="utf-8"))
    me18 = next(case for case in testbook["cases"] if case["id"] == "ME18")
    assert me18["requirement"] == "Actual writer read capability"
    assert me18["current_revision_status"] == "PASS_AUTOMATED_AWS"
    assert "34894779949" in me18["current_revision_observed_result_evidence"]
    assert "not a publication drill or human signoff" in (
        me18["current_revision_observed_result_evidence"]
    )
    assert "PASS_AUTOMATED_AWS" in testbook["current_public_proof"]["writer_read_capability_ME18"]
    for path in ("README.md", "docs/evidence.md", "frontend/UAT.testbook.html",
                 "frontend/public/acceptance.html"):
        text = _flat(path)
        assert "34894779949" in text, path
        assert "not a publication drill" in text, path
    script = _flat("docs/video-script.md")
    for phrase in ("My sandbox", "Start over in a new sandbox", "Shared demo records",
                   "known contradictory offer-4471 record"):
        assert phrase in script
    narration = _flat("video/narration.json")
    assert "select My sandbox and start a fresh workspace" in narration


def test_current_claims_drop_unreproducible_or_overbroad_language():
    paths = [
        "README.md", "docs/devpost-description.md", "docs/architecture.md",
        "docs/cost-and-latency.md", "docs/evidence.md", "docs/video-script.md",
        "docs/video/cards.html", "frontend/src/ArchitectureView.tsx",
        "frontend/src/UserJourneysView.tsx", "frontend/src/OfferDetail.tsx",
        "frontend/src/Pickups.tsx", "video/narration.json",
    ]
    forbidden = (
        "$1.62", "Strands runs each specialist", "four specialists run as",
        "three separate facts", "permanent public", "public sources",
        "cannot run up cost", "at 5 reader errors",
        "superseded record stays served with a notice",
    )
    for path in paths:
        text = _flat(path)
        for phrase in forbidden:
            assert phrase not in text, f"{path}: {phrase}"


def test_scheduled_reachability_checks_only_the_judge_facing_safe_surfaces():
    workflow = _flat(".github/workflows/still-up.yml")
    for literal in ("d2qnkmlhs7y5fp.cloudfront.net", "release.json", "acceptance.html",
                    "api/version"):
        assert literal in workflow
    for stale_target in ("execute-api", "approve/offer-4471", "offers/new",
                         "merismos-records-e6ac6047", "${ROOT_URL}identity"):
        assert stale_target not in workflow


def test_readme_uses_resolving_badges_and_release_diagram_stays_github_safe():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    ci_badge = ("[![CI](https://github.com/upgradedev/merismos-aws/actions/workflows/"
                "ci.yml/badge.svg?branch=main)]")
    frontend_badge = ("[![Frontend verification](https://github.com/upgradedev/merismos-aws/"
                      "actions/workflows/frontend-ci.yml/badge.svg?branch=main)]")
    assert ci_badge in readme
    assert frontend_badge in readme
    diagram = (ROOT / "docs/release-and-validation.md").read_text(encoding="utf-8")
    block = diagram.split("```mermaid", 1)[1].split("```", 1)[0]
    assert "accTitle:" in block and "accDescr:" in block
    for unsupported in ('[/"', '\\]:::', '>"', '{{"', '[("'):
        assert unsupported not in block
