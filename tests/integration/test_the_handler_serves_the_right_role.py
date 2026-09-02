"""One package, three deployments, and the routes each one will serve.

The assertion that matters is that ``/publish`` is refused to the reader and the
evaluator **by the handler**, before any AWS call, and that ``/identity`` reports
the result of actually attempting the credential rather than a configuration
flag. A boundary that reads a flag is a boundary that is true until somebody
edits the flag.
"""

from __future__ import annotations

import json

import pytest

from merismos import handler


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No AWS in these tests. The handler must work from the local filing."""
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    # Spelled out, not deleted. An unset MERISMOS_MODEL means the deployed
    # default, deliberately, so a deployment cannot quietly run without a model
    # and report the deterministic answer as though a model had agreed. The
    # price is that a test environment has to say it wants the offline path,
    # and the first version of this fixture did not, so the suite hung for two
    # minutes reaching for Bedrock with no credentials.
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    monkeypatch.delenv("MERISMOS_CRITIC_MODEL", raising=False)
    monkeypatch.delenv("MERISMOS_PUBLISH_SECRET", raising=False)
    monkeypatch.delenv("MERISMOS_WAKE_TARGET_ARN", raising=False)


def _event(method: str, path: str, body: dict | None = None) -> dict:
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "body": json.dumps(body or {}),
    }


def _json(reply: dict):
    return json.loads(reply["body"])


@pytest.mark.parametrize("me", ["reader", "evaluator", "writer"])
def test_every_deployment_answers_identity(monkeypatch, me):
    """All three carry every route, which is why the role check has to exist."""
    monkeypatch.setenv("MERISMOS_ROLE", me)

    reply = handler.handler(_event("GET", "/identity"))

    assert reply["statusCode"] == 200
    assert _json(reply)["role"] == me


@pytest.mark.parametrize("me", ["reader", "evaluator"])
def test_publishing_is_refused_to_everyone_but_the_writer(monkeypatch, me):
    monkeypatch.setenv("MERISMOS_ROLE", me)

    reply = handler.handler(
        _event("POST", "/publish", {"nonce": "n", "key": "records/x.md", "body": "x"})
    )

    assert reply["statusCode"] == 403
    assert "cannot publish a record" in _json(reply)["detail"]


def test_the_refusal_happens_before_any_aws_call(monkeypatch):
    """Otherwise the boundary would depend on IAM being configured correctly."""
    monkeypatch.setenv("MERISMOS_ROLE", "reader")

    def _explode(*_args, **_kwargs):
        raise AssertionError("the handler reached boto3 before refusing")

    monkeypatch.setattr("boto3.client", _explode)

    reply = handler.handler(
        _event("POST", "/publish", {"nonce": "n", "key": "k", "body": "b"})
    )

    assert reply["statusCode"] == 403


def test_identity_attempts_the_credential_rather_than_reading_a_flag(monkeypatch):
    """The whole argument of the endpoint. It calls, and reports what came back."""
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_PUBLISH_SECRET", "merismos/publish")
    attempted: list[str] = []

    class _Refusing:
        def get_secret_value(self, SecretId: str):  # noqa: N803 - boto3's name
            attempted.append(SecretId)
            raise _AccessDeniedException("not authorized to perform secretsmanager:GetSecretValue")

    monkeypatch.setattr("boto3.client", lambda *_a, **_k: _Refusing())

    reported = _json(handler.handler(_event("GET", "/identity")))

    assert attempted == ["merismos/publish"], "identity did not actually try"
    assert reported["reaches_publish_credential"] is False
    assert reported["what_aws_said"] == "_AccessDeniedException"
    assert "not a flag" in reported["note"]


def test_identity_reports_a_grant_when_the_credential_is_reachable(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_PUBLISH_SECRET", "merismos/publish")

    class _Granting:
        def get_secret_value(self, SecretId: str):  # noqa: N803
            return {"SecretString": "a-token"}

    monkeypatch.setattr("boto3.client", lambda *_a, **_k: _Granting())

    reported = _json(handler.handler(_event("GET", "/identity")))

    assert reported["reaches_publish_credential"] is True
    assert reported["may_publish"] is True


def test_identity_never_returns_the_credential_itself(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_PUBLISH_SECRET", "merismos/publish")

    class _Granting:
        def get_secret_value(self, SecretId: str):  # noqa: N803
            return {"SecretString": "super-secret-token-value"}

    monkeypatch.setattr("boto3.client", lambda *_a, **_k: _Granting())

    reply = handler.handler(_event("GET", "/identity"))

    assert "super-secret-token-value" not in reply["body"]


def test_the_catalogue_is_served_and_names_every_specialist(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")

    served = _json(handler.handler(_event("GET", "/catalog")))["specialists"]

    assert set(served) == {"food-safety", "capacity", "equity", "premises"}
    assert served["premises"]["why"]


def test_config_publishes_the_bounds_this_fleet_claims(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")

    published = _json(handler.handler(_event("GET", "/config")))

    assert published["read_budget_per_run"] == 12
    assert published["read_scope"] == ["offers/", "orgs/", "registers/"]
    assert published["deferrals_wake_on_a_schedule"] is False


def test_an_anonymous_run_reaches_a_card_and_stops(monkeypatch):
    """Safe because a run cannot end in a write, not because it is authenticated."""
    monkeypatch.setenv("MERISMOS_ROLE", "reader")

    result = _json(handler.handler(_event("POST", "/run", {"offer": "offer-4471"})))

    assert result["outcome"] == "awaiting_approval"
    assert result["approval_card"] is None, "a trigger must not approve for a person"


def test_an_anonymous_run_on_a_refused_offer_reports_the_refusal(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")

    result = _json(handler.handler(_event("POST", "/run", {"offer": "offer-4477"})))

    assert result["outcome"] == "blocked"
    assert "cold chain" in result["note"]


def test_an_unknown_route_says_which_role_refused_it(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "evaluator")

    reply = handler.handler(_event("GET", "/nonsense"))

    assert reply["statusCode"] == 404
    assert "evaluator" in _json(reply)["detail"]


def test_an_internal_failure_never_leaks_a_stack_trace(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setattr(
        handler, "catalogue", lambda: (_ for _ in ()).throw(RuntimeError("secret/path/leaked"))
    )

    reply = handler.handler(_event("GET", "/catalog"))

    assert reply["statusCode"] == 500
    assert "secret/path/leaked" not in reply["body"]
    assert _json(reply)["detail"] == "RuntimeError"


# --------------------------------------------------------------------------
# The scheduled wake.
# --------------------------------------------------------------------------


def test_a_scheduled_wake_appends_an_escalation_and_publishes_nothing(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")

    reply = handler.handler(
        {
            "source": "merismos.deferral",
            "deferral_id": "d1",
            "subject": "kypseli-network:offers/chilled",
            "run_id": "run-1",
        }
    )

    body = _json(reply)
    assert body["escalated"] == "d1"
    assert "cannot publish" in body["note"]


def test_a_wake_is_recognised_before_any_http_routing(monkeypatch):
    """A scheduler payload has no requestContext, so this must not 404."""
    monkeypatch.setenv("MERISMOS_ROLE", "reader")

    reply = handler.handler({"source": "merismos.deferral", "deferral_id": "d2"})

    assert reply["statusCode"] == 200


def test_approving_needs_a_named_person_and_is_not_routed(monkeypatch):
    """Not reachable from the handler: this build has no sign-in.

    Wiring approval to an open endpoint would be the shape of the hole the whole
    design exists to close, so it is a function the CLI and the tests call.
    """
    monkeypatch.setenv("MERISMOS_ROLE", "reader")

    reply = handler.handler(_event("POST", "/approve", {"key": "k", "body": "b"}))

    assert reply["statusCode"] == 404

    card = handler.approve(
        {"key": "records/x.md", "body": "bytes", "approved_by": "the coordinator"}
    )
    assert card["approved_by"] == "the coordinator"
    assert card["content_digest"]


def test_a_base64_body_is_decoded(monkeypatch):
    """Function URLs base64 encode a body when the content type says binary."""
    import base64

    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    event = {
        "requestContext": {"http": {"method": "POST", "path": "/run"}},
        "body": base64.b64encode(json.dumps({"offer": "offer-4477"}).encode()).decode(),
        "isBase64Encoded": True,
    }

    assert _json(handler.handler(event))["outcome"] == "blocked"


def test_a_malformed_body_does_not_take_the_run_down(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    event = {
        "requestContext": {"http": {"method": "POST", "path": "/run"}},
        "body": "{not json",
    }

    assert handler.handler(event)["statusCode"] == 200


def test_the_role_comes_from_the_environment_and_not_from_the_request(monkeypatch):
    """A request that could name its role could name its privileges."""
    monkeypatch.setenv("MERISMOS_ROLE", "reader")

    reply = handler.handler(
        _event("POST", "/publish", {"role": "writer", "nonce": "n", "key": "k", "body": "b"})
    )

    assert reply["statusCode"] == 403


class _AccessDeniedException(Exception):
    """Stands in for botocore's generated error class, by name."""
