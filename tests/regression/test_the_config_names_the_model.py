"""`/config` published the bounds and never said whether a model was running.

Its own docstring: "The bounds this fleet publishes about itself, readable with
no account." It lists the read budget, the scope, the byte cap and which ledger
is in use, and the terraform comment beside ``MERISMOS_LEDGER`` gives the reason
in plain words: which store is running is exactly the kind of thing this project
refuses to leave implicit.

It then left the model implicit, which is the single thing a reader of an agent
entry most wants to establish, and the thing this week caught being wrong three
separate times. Every one of those would have been one line here.
"""

from __future__ import annotations

import pytest

from merismos import handler


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.delenv("MERISMOS_CRITIC_MODEL", raising=False)


def test_the_bounds_endpoint_says_whether_a_model_is_running(monkeypatch):
    monkeypatch.setenv("MERISMOS_MODEL", "eu.anthropic.claude-opus-5")

    assert handler.config()["analyst"] == "eu.anthropic.claude-opus-5"


def test_no_model_is_stated_rather_than_omitted(monkeypatch):
    """An absent key reads as "not applicable". This one is a claim."""
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    reported = handler.config()["analyst"]

    assert reported.startswith("none")
    assert "no agent is constructed" in reported


def test_unset_is_not_silently_the_same_as_configured(monkeypatch):
    monkeypatch.delenv("MERISMOS_MODEL", raising=False)

    assert "unset" in handler.config()["analyst"]


def test_the_scripted_path_is_distinguished_from_a_real_model(monkeypatch):
    """Not a boolean, because "a model is configured" cannot tell these apart.

    A Bedrock inference profile and a scripted planner driving the same agent
    loop are different claims about what a run means, and a reader deciding
    whether to believe a record needs the difference.
    """
    monkeypatch.setenv("MERISMOS_MODEL", "scripted")
    reported = handler.config()["analyst"]

    assert "scripted-planner" in reported
    assert "no network" in reported
    assert "eu.anthropic" not in reported


def test_the_identity_that_answered_is_named(monkeypatch):
    """The whole boundary argument turns on which of the three answered."""
    monkeypatch.setenv("MERISMOS_ROLE", "writer")

    assert handler.config()["role"] == "writer"


def test_the_critic_is_reported_and_defaults_to_none(monkeypatch):
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    assert handler.config()["critic"] == "none"

    monkeypatch.setenv("MERISMOS_CRITIC_MODEL", "eu.amazon.nova-pro-v1:0")
    assert handler.config()["critic"] == "eu.amazon.nova-pro-v1:0"


def test_the_bounds_it_always_published_are_still_there():
    """A new field must not have displaced the ones the README points at."""
    reported = handler.config()

    for key in (
        "network",
        "read_scope",
        "read_budget_per_specialist",
        "max_bytes_per_read",
        "ledger",
    ):
        assert key in reported, f"{key} disappeared from the published bounds"
