"""Two records for one offer, disagreeing, and nothing to say which one counts.

``record_key`` never overwrites: a correction takes the next key in the series
and the original stays exactly where it is. That is right on its own and
incomplete on its own. A reader following the published list finds
``offer-4471.md`` giving 96 kg to the pantry and ``offer-4471-c2.md`` giving it
to nobody, with no way to tell which one the network stands behind.

``record_key``'s docstring claimed the index handled this. It did not. A comment
describing behaviour the code does not have is the defect this week has been
about, and that one was written yesterday, here.
"""

from __future__ import annotations

from merismos.handler import _mark_superseded


def rows(*keys: str) -> list[dict]:
    return [
        {"key": k, "url": "https://example.invalid/" + k, "approved_by": "a person"}
        for k in keys
    ]


def marks(*keys: str) -> dict[str, str]:
    return {r["key"]: r["superseded_by"] for r in _mark_superseded(rows(*keys))}


def test_a_single_record_is_not_superseded_by_anything():
    assert marks("records/offer-4471.md") == {"records/offer-4471.md": ""}


def test_the_original_is_marked_and_the_correction_is_the_one_that_stands():
    result = marks("records/offer-4471.md", "records/offer-4471-c2.md")

    assert result["records/offer-4471.md"] == "records/offer-4471-c2.md"
    assert result["records/offer-4471-c2.md"] == ""


def test_the_marking_does_not_depend_on_the_order_the_ledger_returned_them():
    """Recall order is not guaranteed, and guessing from it marks the wrong one."""
    forwards = marks("records/offer-4471.md", "records/offer-4471-c2.md")
    backwards = marks("records/offer-4471-c2.md", "records/offer-4471.md")

    assert forwards == backwards


def test_the_newest_correction_wins_even_when_the_series_arrives_shuffled():
    result = marks(
        "records/offer-4471-c3.md",
        "records/offer-4471.md",
        "records/offer-4471-c2.md",
    )

    assert result["records/offer-4471-c3.md"] == ""
    assert result["records/offer-4471.md"] == "records/offer-4471-c3.md"
    assert result["records/offer-4471-c2.md"] == "records/offer-4471-c3.md"


def test_one_offers_corrections_never_supersede_another_offers_record():
    result = marks(
        "records/offer-4471.md",
        "records/offer-4471-c2.md",
        "records/offer-4483.md",
    )

    assert result["records/offer-4483.md"] == "", (
        "a correction to one offer marked an unrelated record superseded, which "
        "would tell a reader to disregard a record that is perfectly good"
    )
