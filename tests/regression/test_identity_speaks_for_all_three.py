"""The README says /identity proves the boundary "from all three identities".

A stranger could reach one. The evaluator and the writer sit behind Function URLs
with ``authorization_type = "AWS_IAM"``, so the two identities whose refusals
carry the whole argument were the two nobody without AWS credentials could check.
The claim was true of the system and unverifiable by the person being asked to
believe it, which is the shape this project spends its README arguing against.

It was fixable rather than merely rewordable. The reader already holds
``lambda:InvokeFunction`` on both, under a statement named
``AskTheOtherTwoAndTheRunner``, so it can ask them and hand back what AWS told
each one.
"""

from __future__ import annotations

import json

import pytest

from merismos import handler


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")


class FakeLambda:
    """Answers as the other two would, without opening a socket."""

    def __init__(self, answers: dict[str, dict]):
        self.answers = answers
        self.asked: list[str] = []

    def invoke(self, FunctionName: str, Payload: bytes):  # noqa: N803 - boto3's spelling
        self.asked.append(FunctionName)
        role = FunctionName.rsplit("-", 1)[-1]
        if role not in self.answers:
            raise RuntimeError("AccessDeniedException")
        body = json.dumps(self.answers[role]).encode("utf-8")

        class Payload_:
            @staticmethod
            def read():
                return json.dumps({"statusCode": 200, "body": body.decode()}).encode()

        return {"Payload": Payload_()}


def refusal(role: str) -> dict:
    return {
        "role": role,
        "publish_authority": {"can_write": role == "writer", "what_aws_said": "AccessDenied"},
        "boundary_canary": {"can_read": False, "what_aws_said": "AccessDeniedException"},
    }


@pytest.fixture
def fake_lambda(monkeypatch):
    client = FakeLambda({"evaluator": refusal("evaluator"), "writer": refusal("writer")})

    class Boto:
        @staticmethod
        def client(name):
            assert name == "lambda"
            return client

    monkeypatch.setitem(__import__("sys").modules, "boto3", Boto)
    return client


def test_the_plain_endpoint_says_where_the_other_two_are():
    """A judge should not have to read the source to find the proof."""
    reported = handler.identity()

    assert "?all=1" in reported["the_other_two"]
    assert "AWS_IAM" in reported["the_other_two"], (
        "it offers the flag without saying why the other two need one"
    )
    assert "others" not in reported, "the plain call fanned out without being asked"


def test_asking_for_all_three_returns_what_aws_told_each(fake_lambda):
    reported = handler.identity(ask_the_others=True)

    assert set(reported["others"]) == {"evaluator", "writer"}
    assert reported["others"]["evaluator"]["publish_authority"]["can_write"] is False
    assert reported["others"]["evaluator"]["boundary_canary"]["what_aws_said"] == (
        "AccessDeniedException"
    )
    assert fake_lambda.asked == ["merismos-evaluator", "merismos-writer"]


def test_the_writer_is_shown_holding_the_authority_the_others_are_refused(fake_lambda):
    """The boundary is only an argument if one identity actually can."""
    others = handler.identity(ask_the_others=True)["others"]

    assert others["writer"]["publish_authority"]["can_write"] is True
    assert others["evaluator"]["publish_authority"]["can_write"] is False


def test_an_identity_that_does_not_answer_is_not_reported_as_denied(monkeypatch):
    """Inventing a denial would be fabricating the evidence this exists to gather."""
    client = FakeLambda({})  # neither answers

    class Boto:
        @staticmethod
        def client(name):
            return client

    monkeypatch.setitem(__import__("sys").modules, "boto3", Boto)

    others = handler.identity(ask_the_others=True)["others"]

    for role in ("evaluator", "writer"):
        assert others[role]["reached"] is False
        assert "publish_authority" not in others[role], (
            "an unreached identity was given a verdict about what AWS would say"
        )
        assert "not a denied one" in others[role]["note"]


def test_the_query_flag_reaches_the_endpoint(fake_lambda):
    """Routed, not just callable."""
    reply = handler.handler(
        {
            "requestContext": {"http": {"method": "GET", "path": "/identity"}},
            "headers": {"content-type": "application/json"},
            "body": "{}",
            "queryStringParameters": {"all": "1"},
        }
    )

    assert "others" in json.loads(reply["body"])
