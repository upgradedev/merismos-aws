"""No test in this suite reaches the network, and none of them use your account.

There was already a fixture that refused sockets, and it was opt in, so it proved
the claim only for the tests that remembered to ask for it. On 2026-09-05 that
gap cost something real and visible.

``test_the_finished_run_renders_from_the_provenance_thread`` called the actual
``background.start``, which asks Lambda to invoke ``merismos-reader``. On a
machine holding AWS credentials that **succeeds**: every local run of the suite
started a genuine nine minute agentic chore on the deployed fleet. Three of them
in flight held three of the reader's five reserved concurrent executions and the
live site answered 503 to strangers for a stretch that morning. The test passed
throughout, on that machine, because the invoke it should never have made worked.
It failed only on CI, where there are no credentials, and it read like a flake.

A green suite that quietly drives production is worse than a red one. Two things
close it, and the second matters as much as the first.

**Every socket to anything but loopback fails the run** and names the address.
Autouse and session wide, patched at ``socket.socket.connect`` rather than at
boto3: patching the SDK would only prove this code does not call the SDK the way
the test expects, while patching the socket proves nothing reached the network by
any route, including one somebody adds later.

**And the suite never sees your credentials.** Fixed fake ones are set, the
credential and config files are pointed at a path that does not exist, and the
instance metadata probe is disabled. Otherwise the suite behaves differently on a
developer's machine from CI, which is precisely how the defect above hid: it
passed where the credentials were and failed where they were not, which is
exactly backwards from where a failure is useful.
"""

from __future__ import annotations

import socket

import pytest


class NetworkUsedInTheOfflineSuite(AssertionError):
    """Raised the moment a test opens a socket to anywhere real."""


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "allow_network: this test genuinely needs a socket. Say why in its docstring.",
    )


@pytest.fixture(autouse=True)
def _the_same_aws_everywhere(monkeypatch, tmp_path_factory):
    """Fake credentials, no profile, no metadata probe. The same on any machine.

    The values are deliberately obvious. Nothing here signs a request that is
    ever sent: every AWS shape in this suite is asserted through botocore's own
    ``Stubber``, which validates against the real service model and answers
    without a socket. What botocore does need is for the credential chain to
    resolve **at once**, because a chain that finds nothing goes looking, and on
    a runner "looking" means the instance metadata service at 169.254.169.254.
    """
    nowhere = tmp_path_factory.mktemp("no-aws-config") / "does-not-exist"
    # Deliberately not shaped like an access key. The first version of this line
    # used a realistic AKIA prefix and the secret scan flagged it within the
    # minute, which is the scan doing its job: a string that looks like a
    # credential in a public repository costs somebody a revocation whether or
    # not it was ever real. botocore does not care about the shape.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "offline-suite-no-account")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "offline-suite-no-account")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(nowhere))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(nowhere))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")


@pytest.fixture(autouse=True)
def _no_network_anywhere(request, monkeypatch):
    """Refuse every outbound connection that is not loopback."""
    if request.node.get_closest_marker("allow_network"):
        return

    real_connect = socket.socket.connect

    def _refuse(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address, *args, **kwargs)
        raise NetworkUsedInTheOfflineSuite(
            f"a test opened a socket to {host}. This suite needs no account and "
            f"no network, and if that reaches AWS it is not a test, it is a "
            f"deployment being driven by a test run"
        )

    monkeypatch.setattr(socket.socket, "connect", _refuse)
