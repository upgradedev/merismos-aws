"""The README says the suite needs no account, no credentials and no network.

That claim was false for nine minutes and nothing went red.

The handler suite reached for Bedrock because ``MERISMOS_MODEL`` was unset in its
fixture, and botocore retried against absent credentials with exponential
backoff. The tests **passed**: 21 passed in 587.34s, where the same 21 take
0.64s once the offline path is spelled. A failure would have been obvious. A
green suite that is 900 times slower than it should be gets attributed to a slow
runner, and the false claim in the README survives.

So the claim is a test. Every socket this process opens is intercepted, and any
attempt to reach anything that is not the loopback fails the run and names the
address it was trying to reach.
"""

from __future__ import annotations

import socket

import pytest

from merismos.corpus import LocalCorpus
from merismos.demo import main
from merismos.fleet import new_run_id, run_chore, subject_for_offer
from merismos.ledger import InMemoryLedger, Thread


class NetworkUsedInTheOfflineSuite(AssertionError):
    """Raised the moment offline code opens a socket to anywhere real."""


@pytest.fixture
def no_network(monkeypatch):
    """Refuse every outbound connection that is not loopback.

    Patched at ``socket.socket.connect`` rather than at boto3, deliberately.
    Patching the SDK would only prove that this code does not call the SDK the
    way this test expects; patching the socket proves nothing reached the
    network by any route, including one added later by somebody else.
    """
    real_connect = socket.socket.connect
    attempts: list[str] = []

    def _refuse(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            attempts.append(host)
            raise NetworkUsedInTheOfflineSuite(
                f"the offline path opened a socket to {host}. The README says "
                f"this needs no network, and that claim is this test"
            )
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    return attempts


def test_the_demo_runs_with_every_socket_refused(no_network, capsys):
    """The exact command the README's quickstart gives a judge."""
    assert main(["--no-colour"]) == 0

    assert no_network == [], f"the demo reached {no_network}"
    assert "OFFLINE PATH" in capsys.readouterr().out


def test_a_whole_chore_runs_with_every_socket_refused(no_network):
    import json

    corpus = LocalCorpus()
    offer = json.loads(corpus.read("offers/offer-4483.json"))
    thread = Thread(
        ledger=InMemoryLedger(),
        subject=subject_for_offer("kypseli-network", offer),
        run_id=new_run_id(),
    )

    result = run_chore(corpus, offer, thread)

    assert result.outcome == "awaiting_approval"
    assert no_network == []


def test_the_handler_serves_a_run_with_every_socket_refused(no_network, monkeypatch):
    """The suite that actually broke this. It is the one worth pinning."""
    import json

    from merismos import handler

    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")

    reply = handler.handler(
        {
            "requestContext": {"http": {"method": "POST", "path": "/run"}},
            "body": json.dumps({"offer": "offer-4471"}),
        }
    )

    assert json.loads(reply["body"])["outcome"] == "awaiting_approval"
    assert no_network == [], f"the handler reached {no_network}"


def test_the_guard_that_would_have_caught_it_actually_catches_it(no_network):
    """A refusal harness nobody has watched fire is a harness nobody should trust.

    Without this, a bug in the fixture above would make every test in this file
    pass by never intercepting anything.
    """
    bedrock = "bedrock.eu-west-1.amazonaws.com"

    with pytest.raises(NetworkUsedInTheOfflineSuite) as raised:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((bedrock, 443))

    assert "no network" in str(raised.value)
    assert no_network == [bedrock]


def test_an_unset_model_is_the_deployed_default_and_that_is_deliberate():
    """Why this file has to exist rather than the default being changed.

    Making an unset variable mean "no model" would have prevented the hang and
    would also mean a deployment that forgot to set it runs the deterministic
    rules and reports them as though a model had agreed. That is the failure
    this project argues against everywhere else, so the default stays and the
    offline path stays something you spell.
    """
    from merismos.bedrock import DEFAULT_MODEL, analyst_from_env

    assert analyst_from_env({}).model_id == DEFAULT_MODEL
    assert analyst_from_env({"MERISMOS_MODEL": "none"}) is None
