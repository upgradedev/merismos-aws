"""The deployed corpus, checked against S3's own API shape.

A network that runs its own fleet points it at its own filing in a bucket. That
adapter is the one that runs in front of a judge and the local one is what CI
uses, so testing only the local one would report a confidence nobody has.

Two behaviours here are easy to get wrong and expensive to notice. Pagination:
a bucket holding more than one page of keys silently returns the first page
only, so a specialist reports that a policy does not exist. And prefix
stripping: a corpus rooted at ``networks/kypseli/`` must present ``orgs/x.json``
to the agent, not ``networks/kypseli/orgs/x.json``, or every scope check refuses
every real path.
"""

from __future__ import annotations

import boto3
import pytest
from botocore.stub import Stubber

from merismos.corpus import (
    LocalCorpus,
    NotInCorpus,
    S3Corpus,
    corpus_from_env,
    offers,
    org_names,
    orgs,
)

BUCKET = "merismos-corpus"


@pytest.fixture
def client():
    return boto3.client("s3", region_name="eu-west-1")


def test_listing_strips_the_prefix_the_agent_should_not_see(client):
    stubber = Stubber(client)
    stubber.add_response(
        "list_objects_v2",
        {
            "Contents": [
                {"Key": "networks/kypseli/orgs/pantry.json"},
                {"Key": "networks/kypseli/registers/retention.md"},
            ],
            "IsTruncated": False,
        },
        {"Bucket": BUCKET, "Prefix": "networks/kypseli"},
    )
    corpus = S3Corpus(bucket=BUCKET, prefix="networks/kypseli", client=client)

    with stubber:
        paths = corpus.list_paths()

    assert paths == ["orgs/pantry.json", "registers/retention.md"]


def test_a_directory_marker_is_not_a_file(client):
    """A zero-byte key ending in a slash is a folder in the console, not content."""
    stubber = Stubber(client)
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "orgs/"}, {"Key": "orgs/pantry.json"}], "IsTruncated": False},
        {"Bucket": BUCKET, "Prefix": ""},
    )
    corpus = S3Corpus(bucket=BUCKET, client=client)

    with stubber:
        assert corpus.list_paths() == ["orgs/pantry.json"]


def test_a_second_page_is_fetched_rather_than_silently_dropped(client):
    """Without this, a specialist reports that a policy it never saw does not exist."""
    stubber = Stubber(client)
    stubber.add_response(
        "list_objects_v2",
        {
            "Contents": [{"Key": "orgs/a.json"}],
            "IsTruncated": True,
            "NextContinuationToken": "page-2",
        },
        {"Bucket": BUCKET, "Prefix": ""},
    )
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "registers/retention.md"}], "IsTruncated": False},
        {"Bucket": BUCKET, "Prefix": "", "ContinuationToken": "page-2"},
    )
    corpus = S3Corpus(bucket=BUCKET, client=client)

    with stubber:
        paths = corpus.list_paths()

    stubber.assert_no_pending_responses()
    assert paths == ["orgs/a.json", "registers/retention.md"]


def test_reading_joins_the_prefix_back_on(client):
    stubber = Stubber(client)
    stubber.add_response(
        "get_object",
        {"Body": _body(b'{"id": "pantry"}')},
        {"Bucket": BUCKET, "Key": "networks/kypseli/orgs/pantry.json"},
    )
    corpus = S3Corpus(bucket=BUCKET, prefix="networks/kypseli", client=client)

    with stubber:
        assert corpus.read("orgs/pantry.json") == '{"id": "pantry"}'


def test_reading_with_no_prefix_uses_the_path_as_the_key(client):
    stubber = Stubber(client)
    stubber.add_response(
        "get_object", {"Body": _body(b"policy")}, {"Bucket": BUCKET, "Key": "registers/x.md"}
    )
    corpus = S3Corpus(bucket=BUCKET, client=client)

    with stubber:
        assert corpus.read("registers/x.md") == "policy"


def test_a_missing_key_is_absence_rather_than_a_raw_aws_error(client):
    """A specialist has to be able to report "not there" without the run dying."""
    stubber = Stubber(client)
    stubber.add_client_error("get_object", service_error_code="NoSuchKey")
    corpus = S3Corpus(bucket=BUCKET, client=client)

    with stubber, pytest.raises(NotInCorpus):
        corpus.read("registers/absent.md")


def test_the_deployed_corpus_refuses_to_exist_without_a_bucket():
    with pytest.raises(ValueError) as raised:
        S3Corpus(bucket="", client=object())

    assert "MERISMOS_CORPUS_BUCKET" in str(raised.value)


def test_the_backend_is_chosen_from_the_environment():
    assert corpus_from_env({"MERISMOS_CORPUS": "local"}).backend == "local"
    assert corpus_from_env({"MERISMOS_CORPUS_BUCKET": BUCKET}).backend == "s3"
    assert corpus_from_env({}).backend == "local"


def test_a_local_corpus_pointed_at_nothing_says_so():
    with pytest.raises(NotInCorpus):
        LocalCorpus(root="C:/dev/solutions/does-not-exist-anywhere")


def test_a_local_read_outside_the_root_is_refused_after_resolution():
    """Two layers: this one is about the filesystem, the tool's is about policy."""
    corpus = LocalCorpus()

    with pytest.raises(NotInCorpus):
        corpus.read("../../../Windows/win.ini")


def test_a_local_read_of_a_directory_is_not_a_file():
    corpus = LocalCorpus()

    with pytest.raises(NotInCorpus):
        corpus.read("orgs")


# --------------------------------------------------------------------------
# The helpers every specialist reads the network through.
# --------------------------------------------------------------------------


def test_the_helpers_read_whatever_corpus_they_are_given(client):
    """Parsed off the same protocol, so a bucket and a directory agree."""
    corpus = LocalCorpus()

    assert [o["id"] for o in offers(corpus)] == [
        "offer-4471",
        "offer-4477",
        "offer-4483",
    ]
    assert len(orgs(corpus)) == 5
    assert "Omonoia Soup Kitchen" in org_names(corpus)


def test_org_names_is_what_the_gate_checks_an_allocation_against():
    """A plausible name for a charity that does not exist must not be publishable."""
    from merismos.gate import Draft, judge

    names = org_names(LocalCorpus())
    draft = Draft(
        body="# Allocation\n\nGhost Relief Trust: 40 kg",
        allocations=[{"org": "Ghost Relief Trust", "quantity": 40}],
        offer={"quantity": 240},
        known_orgs=names,
    )

    verdict = judge(draft)

    assert verdict.passed is False
    assert [f.check for f in verdict.findings] == ["org-is-on-the-register"]


def _body(payload: bytes):
    """S3 hands back a streaming body, so the stub has to as well."""
    from io import BytesIO

    from botocore.response import StreamingBody

    return StreamingBody(BytesIO(payload), len(payload))
