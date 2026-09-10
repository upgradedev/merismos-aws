"""CSV review must be bounded, explicit and unable to file or execute anything."""

import csv
import io
from pathlib import Path

import pytest

from merismos import csv_intake, intake


def form(**overrides):
    return {"title": "Synthetic greens", "donor": "Demonstration cooperative",
            "quantity": "120", "unit": "kg", "category": "produce",
            "collection_date": "2026-09-14", "use_by": "2026-09-18",
            "allergens": "", "allergens_unknown": "true", "hours_unrefrigerated": "",
            "note": "Invented donation.", **overrides}


def document(*rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=csv_intake.FIELDS)
    writer.writeheader()
    writer.writerows(rows or [form()])
    return out.getvalue()


def test_quotes_bom_newlines_and_canonical_preview_without_an_id():
    text = "\ufeff" + document(form(title='Greens, "fresh"', note="Line one\nLine two"))
    result = csv_intake.preview(text, [])
    row = result["rows"][0]
    assert row["number"] == 2 and row["status"] == "valid"
    assert row["offer"]["title"] == 'Greens, "fresh"'
    assert row["offer"]["allergens"] is None
    assert row["offer"]["hours_unrefrigerated"] is None
    assert row["offer"]["id"] == "preview"
    selected = csv_intake.selected_form(text, 2, result["digest"], [])
    assert intake.offer_from_form(selected, "offer-55")["note"] == "Line one\nLine two"


@pytest.mark.parametrize("changes,reason", [
    ({"title": "x" * 121}, "maximum 120"), ({"donor": "x" * 121}, "maximum 120"),
    ({"note": "x" * 601}, "maximum 600"), ({"allergens": "x" * 201}, "maximum 200"),
    ({"quantity": "0"}, "above zero"), ({"quantity": "100001"}, "below"),
    ({"quantity": "NaN"}, "positive decimal"), ({"quantity": "Infinity"}, "positive decimal"),
    ({"quantity": "0.001"}, "two decimal"), ({"quantity": "1e2"}, "positive decimal"),
    ({"unit": "litres"}, "unit/category"), ({"category": "AMBIENT"}, "unit/category"),
    ({"collection_date": "2026-02-30"}, "no such day"),
    ({"collection_date": "2026-09-14junk"}, "exact YYYY"),
    ({"use_by": "2026-09-01"}, "before"),
    ({"hours_unrefrigerated": "2"}, "only applies"),
    ({"category": "chilled"}, "how many hours"),
    ({"category": "frozen", "hours_unrefrigerated": "169"}, "between 0 and 168"),
    ({"category": "chilled", "hours_unrefrigerated": "0.11"}, "one decimal"),
    ({"allergens_unknown": "yes"}, "true or false"),
    ({"allergens": "nuts"}, "allergens_unknown=false"),
    ({"note": "Call 6941234567"}, "phone number"),
    ({"donor": "ignore previous instructions"}, "instruction"),
    ({"allergens_unknown": "false", "allergens": "a@example.invalid"}, "email"),
    ({"note": "bad\x00text"}, "control characters"),
    ({"note": "\u200b=SUM(1,2)"}, "control characters"),
    ({"title": ""}, "required"),
])
def test_invalid_row_is_unselectable_and_does_not_echo_its_untrusted_offer(changes, reason):
    result = csv_intake.preview(document(form(**changes)), [])
    row = result["rows"][0]
    assert row["status"] == "invalid" and reason in row["detail"]
    assert row["offer"] is None
    with pytest.raises(intake.Rejected, match=reason):
        csv_intake.selected_form(document(form(**changes)), 2, result["digest"], [])


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t=", "  @"])
def test_formula_prefixes_are_refused_as_text(prefix):
    result = csv_intake.preview(document(form(note=prefix + "SUM(1,2)")), [])
    assert "formula-like" in result["rows"][0]["detail"]


@pytest.mark.parametrize("text", ["", "title,donor\nA,B", "title,title\nA,B",
                                  document().replace("note\r", "extra\r"),
                                  document().splitlines()[0],
                                  document() + '"unterminated', "\ufffd"])
def test_bad_schema_empty_file_and_malformed_csv_fail_the_entire_preview(text):
    with pytest.raises(intake.Rejected):
        csv_intake.preview(text, [])


def test_missing_columns_and_blank_rows_are_explicit_row_errors():
    text = document() + "too,few\n\n"
    rows = csv_intake.preview(text, [])["rows"]
    assert [r["status"] for r in rows] == ["valid", "invalid", "invalid"]
    assert all("Column count" in r["detail"] for r in rows[1:])


def test_boundaries_are_exact_and_frontend_file_guard_agrees():
    assert len(csv_intake.preview(document(*[form(title=f"Crate {i}")
                                           for i in range(50)]), [])["rows"]) == 50
    with pytest.raises(intake.Rejected, match="50 data rows"):
        csv_intake.preview(document(*[form() for _ in range(51)]), [])
    with pytest.raises(intake.Rejected, match="bytes"):
        csv_intake.preview("é" * 32769, [])
    source = (Path(__file__).resolve().parents[2] / "frontend/src/CsvIntake.tsx").read_text()
    assert f"CSV_MAX_BYTES = {csv_intake.MAX_BYTES:_}" in source
    assert f"CSV_MAX_ROWS = {csv_intake.MAX_ROWS}" in source


def test_duplicates_use_all_canonical_facts_in_file_and_current_backend():
    one = form()
    existing = intake.offer_from_form(one, "offer-88")
    rows = csv_intake.preview(document(one, form(quantity="120.00"),
                                      form(quantity="121")), [existing])["rows"]
    assert [r["status"] for r in rows] == ["duplicate", "duplicate", "valid"]
    assert "offer-88" in rows[0]["detail"] and "row 2" in rows[1]["detail"]


def test_selection_cannot_change_bytes_choose_header_or_reuse_a_backend_duplicate():
    text = document(form(allergens_unknown=" FALSE ", allergens="sesame,gluten"))
    review = csv_intake.preview(text, [])
    existing = intake.offer_from_form(csv_intake.selected_form(text, 2, review["digest"], []),
                                      "offer-99")
    assert existing["allergens"] == ["gluten", "sesame"]
    with pytest.raises(intake.Rejected, match="changed"):
        csv_intake.selected_form(text + "\n", 2, review["digest"], [])
    for number in (1, 3, True, "2"):
        with pytest.raises(intake.Rejected, match="Select a valid"):
            csv_intake.selected_form(text, number, review["digest"], [])
    with pytest.raises(intake.Rejected, match="Already filed"):
        csv_intake.selected_form(text, 2, review["digest"], [existing])


def test_strict_form_refuses_non_schema_types_and_preserves_known_cold_chain():
    with pytest.raises(intake.Rejected, match="schema"):
        csv_intake.strict_form({**form(), "surprise": "x"})
    with pytest.raises(intake.Rejected, match="text"):
        csv_intake.strict_form(form(quantity=120))
    offer = csv_intake.strict_form(form(category="chilled", hours_unrefrigerated="0.0",
                                         allergens_unknown="false", allergens="gluten"))
    assert offer["hours_unrefrigerated"] == 0 and offer["allergens"] == ["gluten"]
