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
    assert "Try success" in text[:1100]
    assert "Strands" in text
    assert "read-only" in text
    assert "no model network call" in text.replace("\n", " ")
    assert "licen" in text.lower()


def test_narration_and_script_share_bounds_and_do_not_claim_automatic_delivery():
    data = json.loads((ROOT / "video/narration.json").read_text(encoding="utf-8"))
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
