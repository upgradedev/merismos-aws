"""Every sandbox offer said "Date passed" five days after the corpus was written.

The seeded offers carry the dates they were written with: 2026-09-08, 09 and 10.
A sandbox opened on the 13th put "Date passed" on all three, and the first thing
a judge read about a food-allocation tool was that its food had expired. The
dates are fixture, not fact. What the rules read is the interval between them:
offer-4471's use-by is the day after collection, which is what makes it a
same-day offer, and that has to survive the move.

Registers and manifests are not moved. Their dates say when a policy was agreed,
and a policy agreed "today" every time a sandbox opens would be a lie of a
different kind.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest

from merismos import api, handler
from merismos.ledger import reset_memory_ledger


class Frozen(date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 2)


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("MERISMOS_OFFLINE_HTTP", "1")
    monkeypatch.setenv("MERISMOS_WORKSPACE_DB", str(tmp_path / "workspace.sqlite"))
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_MODEL", "scripted")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setattr(api, "date", Frozen)
    reset_memory_ledger()


def open_sandbox() -> str:
    response = handler.handler({
        "requestContext": {"http": {"method": "POST", "path": "/api/sessions"}},
        "headers": {}, "body": "{}",
    })
    assert response["statusCode"] == 201
    return json.loads(response["body"])["session"]


def seeded_offers() -> dict[str, dict]:
    state = api.WorkspaceStore().get(api.fingerprint(open_sandbox()))
    return {path: json.loads(text) for path, text in state["files"].items()
            if path.startswith("offers/") and path.endswith(".json")}


def shipped_seed() -> dict:
    return json.loads(api.files("merismos").joinpath("demo_corpus.json").read_text())


def test_no_seeded_offer_is_in_the_past_when_the_sandbox_opens():
    for path, offer in seeded_offers().items():
        assert offer["collection_date"] > Frozen.today().isoformat(), (
            f"{path} opens already passed; a judge reads a stale demo"
        )


def test_the_earliest_collection_is_tomorrow_and_the_others_follow_in_order():
    offers = seeded_offers()
    tomorrow = Frozen.today() + timedelta(days=1)

    assert offers["offers/offer-4471.json"]["collection_date"] == tomorrow.isoformat()
    assert offers["offers/offer-4477.json"]["collection_date"] == (
        tomorrow + timedelta(days=1)).isoformat()
    assert offers["offers/offer-4483.json"]["collection_date"] == (
        tomorrow + timedelta(days=2)).isoformat()


def test_the_same_day_window_on_offer_4471_survives_the_move():
    """The rule reads use-by minus collection. That interval is the fixture."""
    offer = seeded_offers()["offers/offer-4471.json"]

    collection = date.fromisoformat(offer["collection_date"])
    use_by = date.fromisoformat(offer["use_by"])
    assert (use_by - collection).days == 1


def test_every_interval_is_preserved_and_nothing_but_dates_moves():
    original = shipped_seed()
    for path, offer in seeded_offers().items():
        before = json.loads(original[path])
        was = (date.fromisoformat(before["use_by"])
               - date.fromisoformat(before["collection_date"])).days
        now = (date.fromisoformat(offer["use_by"])
               - date.fromisoformat(offer["collection_date"])).days
        assert was == now, f"{path}: the use-by window changed from {was} to {now} days"
        for key in ("id", "title", "donor", "category", "quantity", "unit",
                    "hours_unrefrigerated", "allergens", "manifest", "note"):
            assert offer[key] == before[key], f"{path}: {key} is not a date and changed"


def test_registers_and_manifests_keep_the_dates_they_were_written_with():
    seed = shipped_seed()
    moved = api.rebase_dates(seed, Frozen.today())

    for path in seed:
        if not (path.startswith("offers/") and path.endswith(".json")):
            assert moved[path] == seed[path], f"{path} is policy, not an offer, and it moved"


def test_a_sandbox_opened_the_day_before_the_anchor_is_left_alone():
    seed = {"offers/offer-1.json": '{"collection_date": "2026-09-08"}'}

    assert api.rebase_dates(seed, date(2026, 9, 7)) == seed


def test_the_moved_offers_still_run_to_the_same_outcomes():
    """The split reads intervals. If the move changed an outcome, it moved the wrong thing."""
    handle = open_sandbox()

    def call(path="/api/workspace", method="GET", data=None):
        reply = handler.handler({
            "requestContext": {"http": {"method": method, "path": path}},
            "headers": {"x-merismos-session": handle},
            "body": json.dumps({"mode": "sandbox", **(data or {})}),
        })
        return reply["statusCode"], json.loads(reply["body"])

    outcomes = {}
    for offer in ("offer-4471", "offer-4477", "offer-4483"):
        _, state = call()
        code, state = call(f"/api/offers/{offer}/run", "POST",
                           {"version": state["version"], "request_id": uuid.uuid4().hex})
        assert code == 200, state
        row = next(o for o in state["offers"] if o["offer"]["id"] == offer)
        outcomes[offer] = row["result"]["outcome"]

    assert outcomes == {"offer-4471": "awaiting_approval", "offer-4477": "blocked",
                        "offer-4483": "awaiting_approval"}
