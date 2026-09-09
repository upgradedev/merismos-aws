"""The read bound has two locks offline and one in production.

``LocalCorpus.read`` resolves the path and refuses anything landing outside the
corpus root, which catches a symlink escape too; its own comment calls that the
filesystem layer and ``check_read`` the policy layer. ``S3Corpus.read``
interpolates the path straight into a ``get_object`` key and has no second layer
at all. So every test of this bound has run against the pair, and on the deployed
path ``check_read`` stands alone.

That asymmetry is the finding. It is the same shape as the model configured on
the function that did not run the chore: **the thing being tested is not the
thing that runs**, and the gap stays invisible until something downstream
changes.

Probing ``check_read`` with twelve paths found two it allowed:
``orgs/%2e%2e/%2e%2e/etc/passwd`` and a path carrying a null byte. **Neither was
exploitable**, and recording them as though they were would be the overclaim this
module exists to refuse: S3 keys are flat, so ``..`` is not traversal there, and
both resolve to keys that do not exist. They are refused because a corpus path
contains neither a percent sign nor a control character, and a bound that passes
because something downstream happens to catch it is a bound that fails when the
downstream changes.
"""

from __future__ import annotations

import pytest

from merismos.tools import DEFAULT_SCOPE, ReadLog, ReadRefused, check_read


def allowed(path: str) -> bool:
    try:
        check_read(ReadLog(), path)
        return True
    except ReadRefused:
        return False


# --------------------------------------------------------------------------
# What the boundary must refuse on its own.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "../secrets.json",
        "orgs/../../etc/passwd",
        "/etc/passwd",
        "C:/Windows/System32/config/SAM",
        r"orgs\..\..\etc\passwd",
        "https://example.invalid/x",
        "records/offer-4471.md",
        "notorgs/evil.json",
        "orgs//../../etc/passwd",
    ],
)
def test_the_shapes_it_already_refused_are_still_refused(path):
    assert not allowed(path)


def test_a_percent_encoded_path_is_refused():
    """Not exploitable, and not a path either. It is refused where the bound lives."""
    assert not allowed("orgs/%2e%2e/%2e%2e/etc/passwd")
    assert not allowed("orgs/a%20b.json")


def test_a_control_character_is_refused():
    """A null byte in a path is not a typo."""
    assert not allowed("orgs/x.json\x00.txt")
    assert not allowed("orgs/x\ty.json")


def test_an_ordinary_path_in_every_scoped_prefix_still_reads():
    """A bound that refuses the real thing is worse than one that is loose."""
    for prefix in DEFAULT_SCOPE:
        assert allowed(f"{prefix}something.json"), f"{prefix} became unreachable"


def test_the_refusal_says_which_rule_refused_it():
    """A refused read is recorded and shown, so the reason has to be usable."""
    with pytest.raises(ReadRefused) as encoded:
        check_read(ReadLog(), "orgs/%2e%2e/x")
    assert "percent encoded" in str(encoded.value)

    with pytest.raises(ReadRefused) as control:
        check_read(ReadLog(), "orgs/x\x00")
    assert "control character" in str(control.value)


# --------------------------------------------------------------------------
# The asymmetry itself, written down where it will be read.
# --------------------------------------------------------------------------


def test_the_two_corpus_backends_do_not_agree_about_a_second_lock():
    """Recorded rather than fixed, and the reason is in the test name.

    Giving ``S3Corpus.read`` a second layer means listing the bucket on every
    read, a cost paid on every specialist read of every run to close a gap that
    ``check_read`` already closes, and S3 has no traversal for a containment
    check to catch. What is worth having is the fact stated: if
    this ever stops being true, the bound above is the only one left and it had
    better be complete.
    """
    import inspect

    from merismos.corpus import LocalCorpus, S3Corpus

    local = inspect.getsource(LocalCorpus.read)
    s3 = inspect.getsource(S3Corpus.read)

    assert "resolve()" in local and "outside the corpus" in local, (
        "the offline path lost its containment check, so the two backends now "
        "agree by the offline one getting weaker rather than the other stronger"
    )
    assert "resolve" not in s3 and "startswith" not in s3, (
        "S3Corpus grew a second layer, so this asymmetry is closed and this test "
        "should go along with the comment in check_read that cites it"
    )
