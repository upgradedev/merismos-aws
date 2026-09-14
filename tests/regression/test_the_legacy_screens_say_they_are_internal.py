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


def the_shell() -> tuple[str, str, str]:
    """``page()``'s own opening, top and closing, taken from ``page()`` rather than typed here.

    The opening stops at the robots meta because ``page()`` puts the waiting
    screen's refresh meta straight after it. The top runs from the stylesheet
    through the notice and the header to the opening of ``<main>``.
    """
    shell = web.page("Probe", "<h1>Probe</h1>")
    opening = shell[: shell.index(NOINDEX) + len(NOINDEX)]
    main = '<main id="main" class="wrap">'
    top = shell[shell.index("<style>") : shell.index(main) + len(main)]
    closing = shell[shell.index("</main>") :]
    return opening, top, closing


def assert_built_by_the_shell(page: str) -> None:
    opening, top, closing = the_shell()
    assert NOTICE in top, "the probe shell no longer carries the notice"
    assert page.startswith(opening), "this document was not opened by web.page()"
    assert page.count(top) == 1, "the stylesheet, notice and header are not page()'s own"
    assert page.endswith(closing), "this document was not closed by web.page()"
    assert page.lower().count("<!doctype") == 1, "a second document is inside this one"


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
    decided = call("/offer/offer-4471", query={"run": a_run("offer-4471")})["body"]
    refused = call("/offer/offer-4477", query={"run": a_run("offer-4477")})["body"]
    for page in (
        decided,
        refused,
        call("/approve/offer-4471", query={"run": a_run("offer-4471")})["body"],
    ):
        assert_labelled(page)
        assert_built_by_the_shell(page)
    card = call("/approve/offer-4471", query={"run": a_run("offer-4471")})["body"]
    assert "What will be published" in card, "this walked past the card rather than to it"
    assert "<h2>The split</h2>" in decided, "this is not the decision screen"
    # A waiting page or a failed run carries the notice too, so only the
    # refusal heading proves this reached the refusal.
    assert "<strong>Refused, and here is why.</strong>" in refused, "this is not the refusal"
    assert "The fleet is reading" not in refused and "The run failed" not in refused


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
        assert_built_by_the_shell(page)


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


def test_every_html_reply_the_handler_gives_is_built_by_the_shell(run_now):
    """Every text/html reply ``handler.handler`` gives on these routes is ``page()``'s document.

    The count above only reads source text. This asks the handler itself, for
    every server-rendered route this file exercises and the screens behind a
    run, and checks that each HTML reply is opened, topped and closed by
    ``page()`` with the notice in it.

    ``POST /offers/new`` is in the set because it is the refusal a stranger
    gets. The coordinator API refuses it before the legacy form code is
    reached, so the refusal is JSON rather than a page. It is pinned here as
    exactly that, so it cannot become an HTML document that skipped the shell.
    """
    replies = {f"GET {path}": call(path) for path, _ in ROUTES}
    for path in ("/offer/offer-4471", "/offer/offer-4477", "/approve/offer-4471"):
        offer_id = path.rsplit("/", 1)[-1]
        replies[f"GET {path}?run"] = call(path, query={"run": a_run(offer_id)})
    replies["POST /offers/new"] = call("/offers/new", method="POST")

    html_replies = {
        name for name, reply in replies.items()
        if "text/html" in reply["headers"]["content-type"] or "<!doctype" in reply["body"].lower()
    }
    assert html_replies == set(replies) - {"POST /offers/new"}
    for name in sorted(html_replies):
        assert_labelled(replies[name]["body"])
        assert_built_by_the_shell(replies[name]["body"])

    refused = replies["GET /offer/offer-4477?run"]["body"]
    assert "<strong>Refused, and here is why.</strong>" in refused, "this is not the refusal"

    refusal = replies["POST /offers/new"]
    assert refusal["statusCode"] == 403
    assert refusal["headers"]["content-type"] == "application/json"
    assert json.loads(refusal["body"])["detail"].startswith(
        "Live changes require an authenticated network coordinator."
    )
    assert NOTICE not in refusal["body"]


# --------------------------------------------------------------------------
# The app address: from the environment, http or https only, always escaped.
# --------------------------------------------------------------------------


def test_the_app_address_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MERISMOS_APP_URL", "https://app.example.invalid/merismos")
    app = "https://app.example.invalid/merismos"

    assert web.app_url() == app
    assert_labelled(call("/")["body"], app)
    assert f'href="{app}#/offers/new"' in web.new_offer_form()


@pytest.mark.parametrize(("value", "app"), [
    ("https://app.example.invalid", "https://app.example.invalid/"),
    ("https://app.example.invalid/merismos/", "https://app.example.invalid/merismos/"),
    ("https://app.example.invalid/app/index.html", "https://app.example.invalid/app/index.html"),
    ("http://APP.example.invalid:8080/app", "http://app.example.invalid:8080/app"),
    ("http://[::1]:8080", "http://[::1]:8080/"),
    ("https://app.example.invalid:443/?q=1#frag", "https://app.example.invalid:443/"),
])
def test_only_an_empty_path_becomes_a_slash(monkeypatch, value, app):
    monkeypatch.setenv("MERISMOS_APP_URL", value)

    assert web.app_url() == app
    assert_labelled(call("/")["body"], app)


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
    # A username or password would be printed on every page.
    "https://user@app.example.invalid/",
    "https://user:secret@app.example.invalid/",
    "https://:secret@app.example.invalid/",
    "https://@app.example.invalid/",
    # A port that is not a port.
    "https://app.example.invalid:99999/",
    "https://app.example.invalid:port/",
    "https://app.example.invalid:-1/",
    # No host.
    "https://:443/",
    "http:///merismos",
    "https://user:secret@/",
])
def test_anything_but_an_http_or_https_address_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("MERISMOS_APP_URL", value)

    assert web.app_url() == DEFAULT
    page = call("/")["body"]
    assert_labelled(page)
    assert "secret" not in page and "user@" not in page, "a credential reached the page"
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
        "max_files_per_search", "max_request_body_bytes", "max_request_body_depth", "network",
        "read_budget_per_specialist", "read_scope", "role",
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
