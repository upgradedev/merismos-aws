"""Two personal data checks existed and missed the local case they are for.

`_NATIONAL_ID` matched AMKA and the British NI number. **AFM was not in it**, and
AFM is the Greek tax number, the identifier most often written down here, in a
product set in one Athens neighbourhood.

`_NAMED_HOUSEHOLD` required a courtesy title, so "collected by Mrs Papadopoulou"
was caught and "the Papadopoulos family collected it" was not. Its own comment
says what it is for: a household named as a recipient rather than counted.
Naming a family without a title is how anybody would actually write it.

Both reach a public, permanent record.
"""

from __future__ import annotations

import pytest

from merismos import gate
from merismos.corpus import LocalCorpus, org_names


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")


def checks(body: str) -> set[str]:
    draft = gate.Draft(
        body=body,
        allocations=[{"org": "Omonoia Soup Kitchen", "quantity": 10.0, "reason": "x"}],
        offer={"id": "offer-x", "quantity": 100, "unit": "kg"},
        known_orgs=org_names(LocalCorpus()),
    )
    return {f.check for f in gate.check_personal_data(draft)}


@pytest.mark.parametrize(
    "written",
    ["AFM 123456789", "A.F.M.: 123456789", "afm 123456789", "ΑΦΜ 123456789"],
)
def test_a_greek_tax_number_is_caught_however_it_is_written(written):
    assert "no-national-id" in checks(f"Collected on Tuesday. {written}")


def test_the_identifiers_that_were_already_caught_still_are():
    assert "no-national-id" in checks("AMKA 12345678901")
    assert "no-email" in checks("write to nobody@example.com")
    assert "no-phone-number" in checks("ring 694 412 3456")


@pytest.mark.parametrize(
    "written",
    [
        "The Papadopoulos family collected it",
        "given to the Papadopoulos family",
        "the Nikolaou household took the rest",
        "collected by Mrs Papadopoulou",
    ],
)
def test_a_named_household_is_caught_with_or_without_a_courtesy_title(written):
    assert "no-named-household" in checks(written)


@pytest.mark.parametrize(
    "written",
    [
        "Omonoia Soup Kitchen 96 kg, allocated under the 40% cap",
        "donated by the Fokionos bakery",
        "the food family of products",
        "41 households served weekly",
    ],
)
def test_ordinary_record_text_is_not_refused(written):
    """A gate that refuses the real thing is worse than one that is loose."""
    assert not checks(written)


def test_the_case_flag_was_not_used_because_it_would_loosen_the_name():
    """``[Tt]he`` rather than ``re.IGNORECASE``, which would match "the food family"."""
    assert "no-named-household" in checks("The Papadopoulos family")
    assert "no-named-household" not in checks("the food family of products")


def test_the_networks_own_filing_still_passes_every_pattern():
    """A register that spells out a forbidden example can put one in a record.

    ``retention.md`` illustrated the rule with a named family. A specialist reads
    that register and can quote it into a finding, and a finding reaches the
    published record, so the register now describes the shape rather than writing
    one out. This is the narrower version of the suite's corpus-wide check, kept
    here because that is the reason the register was reworded.
    """
    import pathlib

    text = pathlib.Path("corpus/registers/retention.md").read_text(encoding="utf-8")

    assert not checks(text), "the fleet would refuse a record quoting its own register"
    assert "describes the forbidden shape" in text
