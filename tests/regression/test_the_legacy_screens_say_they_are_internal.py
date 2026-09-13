"""Every server-rendered screen says it is an internal view, and no JSON reply changes.

ME11. The product is the React app on CloudFront. The reader Lambda still serves
the older server-rendered screens, because the deploy workflow's proof steps and
this suite fetch them and check their status codes and content, so they are kept
rather than redirected. What changed is that each one now says what it is: a
notice at the top of the body that links to the app, and a robots meta asking not
to be indexed.

The JSON routes are the other half of that promise. Labelling a page for a person
must not change a byte of a reply a script parses.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from merismos import background, handler, web

NOTICE = "Internal compatibility view of the Merismos API, kept for automated checks."
NOINDEX = '<meta name="robots" content="noindex">'
DEFAULT = "https://d2qnkmlhs7y5fp.cloudfront.net/"
SRC = Path(__file__).resolve().parents[2] / "src" / "merismos"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    monkeypatch.delenv("MERISMOS_CRITIC_MODEL", raising=False)
    monkeypatch.delenv("MERISMOS_PUBLISH_SECRET", raising=False)
    monkeypatch.delenv("MERISMOS_RECORDS_BUCKET", raising=False)
    monkeypatch.delenv("MERISMOS_APP_URL", raising=False)


@pytest.fixture
def run_now(monkeypatch):
    """The background hop as a direct call, the same way the screens test walks it."""

    def _straight_through(offer_id: str, run_id: str, network: str) -> None:
        handler._run_in_background({"offer_id": offer_id, "run_id": run_id, "network": network})

    monkeypatch.setattr(background, "start", _straight_through)


def call(path: str, method: str = "GET", query: dict | None = None) -> dict:
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": {"content-type": "application/json"},
        "body": "{}",
        "queryStringParameters": query or {},
    }
    if method == "POST" and path.startswith("/offer/"):
        event["requestContext"]["authorizer"] = {"lambda": {
            "network": handler.NETWORK, "principalId": "fixture-coordinator",
            "permissions": ["merismos:coordinate"]}}
    return handler.handler(event)


def a_run(offer_id: str) -> str:
    started = call(f"/offer/{offer_id}", method="POST")
    assert started["statusCode"] == 303, started
    return started["headers"]["location"].split("run=", 1)[1]


def assert_labelled(page: str, app: str = DEFAULT) -> None:
    assert NOINDEX in page, "the screen can be indexed"
    head, _, body = page.partition("<body>")
    assert NOINDEX in head, "the robots meta is not in the head"
    assert NOTICE in body, "the screen does not say it is an internal view"
    # At the top of the body: before the header, the navigation and the content.
    assert body.index(NOTICE) < body.index('<header class="top">') < body.index('<main id="main"')
    assert f'The Merismos app is at <a href="{app}">{app}</a>.' in body


# --------------------------------------------------------------------------
# Every screen, by route, with the status code it already had.
# --------------------------------------------------------------------------

#: Every server-rendered route reachable with a plain GET, and its status today.
#: The labels must not move a status code: deploy.yml checks them.
ROUTES = [
    ("/", 200),
    ("/how", 200),
    ("/offer/offer-4471", 200),
    ("/offer/offer-9999", 404),
    ("/approve/offer-4471", 404),
    ("/offers/new", 200),
    ("/records", 200),
    ("/record/offer-4471", 404),
    ("/chain/offer-4471", 200),
]


@pytest.mark.parametrize(("path", "status"), ROUTES)
def test_every_server_rendered_route_carries_the_notice_and_noindex(path, status):
    reply = call(path)

    assert reply["statusCode"] == status
    assert "text/html" in reply["headers"]["content-type"]
    assert_labelled(reply["body"])


def test_the_screens_behind_a_run_carry_it_too(run_now):
    """The decision, the refusal and the approval card only exist for a run."""
    for page in (
        call("/offer/offer-4471", query={"run": a_run("offer-4471")})["body"],
        call("/offer/offer-4477", query={"run": a_run("offer-4477")})["body"],
        call("/approve/offer-4471", query={"run": a_run("offer-4471")})["body"],
    ):
        assert_labelled(page)
    card = call("/approve/offer-4471", query={"run": a_run("offer-4471")})["body"]
    assert "What will be published" in card, "this walked past the card rather than to it"


def test_the_screens_no_route_reaches_offline_carry_it_too():
    """The waiting page and the two record pages, built directly."""
    offer = {"id": "offer-4471", "title": "Bread", "quantity": 240, "unit": "kg"}
    receipt = {"approved_by": "a person", "key": "records/offer-4471.md"}
    for page in (
        web.waiting(offer, "run-1", {"specialists_answered": 1}, "the model"),
        web.published(receipt, "body"),
        web.one_record("records/offer-4471.md", "body", receipt),
        web.page("Anything", "<h1>Anything</h1>"),
    ):
        assert_labelled(page)


def test_no_document_is_built_anywhere_but_the_shell():
    """One place builds an HTML document, so one place carries the label.

    A screen assembled with its own doctype somewhere else would be a screen the
    notice never reached, and every route above could still pass.
    """
    builders = {
        path.name: len(re.findall(r"<!doctype html", path.read_text(encoding="utf-8"), re.I))
        for path in SRC.glob("*.py")
    }
    assert builders.pop("web.py") == 1
    assert not any(builders.values()), builders


# --------------------------------------------------------------------------
# The app address: from the environment, http or https only, always escaped.
# --------------------------------------------------------------------------


def test_the_app_address_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MERISMOS_APP_URL", "https://app.example.invalid/merismos")
    app = "https://app.example.invalid/merismos/"

    assert web.app_url() == app
    assert_labelled(call("/")["body"], app)
    assert f'href="{app}#/offers/new"' in web.new_offer_form()


@pytest.mark.parametrize("value", [
    "",
    "javascript:alert(1)",
    "JAVASCRIPT://example.invalid/%0aalert(1)",
    "data:text/html,<b>x</b>",
    "ftp://files.example.invalid/",
    "d2qnkmlhs7y5fp.cloudfront.net",
    "https://",
    "https://exa mple.invalid/",
    "https://example.invalid/\n<b>",
    "http://[::1",
])
def test_anything_but_an_http_or_https_address_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("MERISMOS_APP_URL", value)

    assert web.app_url() == DEFAULT
    page = call("/")["body"]
    assert_labelled(page)
    absolute = re.findall(r'href="([A-Za-z][A-Za-z0-9+.-]*:[^"]*)"', page)
    assert set(absolute) == {DEFAULT}, "a rejected address became a link"


def test_the_app_address_is_escaped_like_every_other_value(monkeypatch):
    monkeypatch.setenv("MERISMOS_APP_URL", 'https://app.example.invalid/a"b<c>/?q=1#frag')

    page = call("/")["body"]

    assert '"b<c>' not in page
    escaped = "https://app.example.invalid/a&quot;b&lt;c&gt;/"
    assert f'The Merismos app is at <a href="{escaped}">{escaped}</a>.' in page
    assert "q=1" not in page and "#frag" not in page


# --------------------------------------------------------------------------
# The JSON routes: same status, same content type, same bytes, same shape.
# --------------------------------------------------------------------------

#: Every JSON route that answers offline, with the top-level keys it has today.
JSON_ROUTES = {
    "/config": [
        "analyst", "critic", "deferrals_wake_on_a_schedule", "ledger", "max_bytes_per_read",
        "max_files_per_search", "network", "read_budget_per_specialist", "read_scope", "role",
    ],
    "/catalog": ["reads_is_expected_not_enforced", "specialists"],
    "/offers": ["offers"],
    "/version": ["application", "commit", "schema_version", "source", "status"],
    "/api/version": ["application", "commit", "schema_version", "source", "status"],
    "/thread": ["detail", "entries", "note", "run_id"],
    "/no-such-route": ["detail"],
}


@pytest.mark.parametrize("path", sorted(JSON_ROUTES))
def test_json_routes_are_byte_for_byte_unchanged_in_shape(monkeypatch, path):
    plain = call(path)
    monkeypatch.setenv("MERISMOS_APP_URL", "https://app.example.invalid/")
    relabelled = call(path)

    assert plain["statusCode"] == relabelled["statusCode"] == (
        404 if path == "/no-such-route" else 200
    )
    assert plain["headers"]["content-type"] == "application/json"
    assert relabelled["headers"]["content-type"] == "application/json"
    assert plain["body"] == relabelled["body"], "the app address reached a JSON reply"
    assert sorted(json.loads(plain["body"])) == JSON_ROUTES[path]
    for label in (NOTICE, "noindex", "app.example.invalid", DEFAULT):
        assert label not in plain["body"]
        assert label not in relabelled["body"]
