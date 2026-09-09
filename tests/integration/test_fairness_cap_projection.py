"""The additive read model reveals one exact policy fraction, never raw metadata."""

import pytest

from merismos.api import public_result


def saved(share=0.4, source="registers/allocation-policy.md"):
    return {"outcome": "awaiting_approval", "draft_body": "Synthetic allocation.",
            "envelopes": [{"specialist": "equity", "status": "ok", "findings": [],
                           "meta": {"ceiling_share": share, "ceiling_from": source,
                                    "private_note": "never expose internal metadata"}}]}


@pytest.mark.parametrize("share", [0.4, 0.25, 0.125, 0.3333333333333333, 1])
def test_exact_applied_fraction_is_not_guessed_from_record_prose(share):
    raw = saved(share)
    raw["draft_body"] = "The rounded display could say 40%; it is not the data source."
    result = public_result(raw)
    assert result["fairness_cap"] == {"share": share, "source": "registers/allocation-policy.md"}
    assert "meta" not in result["envelopes"][0]
    assert "private_note" not in str(result)
    assert result["outcome"] == "awaiting_approval"


@pytest.mark.parametrize("share", [None, True, False, "0.4", 0, -0.1, 1.1,
                                  float("nan"), float("inf"), float("-inf"),
                                  10 ** 1000, {}, []])
def test_invalid_fraction_is_unknown_not_a_fallback(share):
    assert public_result(saved(share))["fairness_cap"] is None


@pytest.mark.parametrize("source", [None, "", "unknown", "call 6941234567", {}, []])
def test_only_permitted_source_labels_are_exported(source):
    result = public_result(saved(source=source))
    assert result["fairness_cap"] is None
    assert "6941234567" not in str(result)


def test_default_is_reported_only_when_the_backend_recorded_it():
    source = "the default, because this filing states no ceiling"
    assert public_result(saved(source=source))["fairness_cap"]["source"] == source


def test_old_missing_ambiguous_and_non_equity_results_have_no_cap():
    assert public_result({"draft_body": "old saved plan: 40%"})["fairness_cap"] is None
    raw = saved()
    raw["envelopes"][0].pop("meta")
    assert public_result(raw)["fairness_cap"] is None
    raw = saved()
    raw["envelopes"][0]["specialist"] = "capacity"
    assert public_result(raw)["fairness_cap"] is None
    raw = saved()
    raw["envelopes"] *= 2
    assert public_result(raw)["fairness_cap"] is None


@pytest.mark.parametrize("meta", [None, [], "40%", {}, {"ceiling_share": 0.4},
                                   {"ceiling_from": "registers/allocation-policy.md"}])
def test_incomplete_or_invalid_metadata_is_not_exposed(meta):
    raw = saved()
    raw["envelopes"][0]["meta"] = meta
    assert public_result(raw)["fairness_cap"] is None


def test_personal_data_refusal_still_removes_the_plan_and_cap():
    raw = saved()
    raw["draft_body"] = "Call 6941234567"
    result = public_result(raw)
    assert result["outcome"] == "refused_by_gate"
    assert not result.get("fairness_cap")
    assert result["draft_body"] == "" and result["envelopes"] == []
