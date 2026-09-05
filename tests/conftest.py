"""No test in this suite reaches the network. Enforced here rather than promised.

There was already a fixture that refused sockets, and it was opt in, so it
proved the claim only for the tests that remembered to ask for it. On 2026-09-05
that gap cost something real and visible.

``test_the_finished_run_renders_from_the_provenance_thread`` called the actual
``background.start``, which asks Lambda to invoke ``merismos-reader``. On a
machine with AWS credentials that **succeeds**: every local run of the suite
started a genuine nine minute agentic chore on the deployed fleet. Three of them
in flight held three of the reader's five reserved concurrent executions and the
live site answered 503 to strangers for a stretch that morning. The test passed
throughout, on that machine, because the invoke it should never have made worked.
It failed only on CI, where there are no credentials, and it read like a flake.

A green suite that quietly drives production is worse than a red one. So the
refusal is autouse and session wide now: every socket to anything but loopback
fails the run and names the address. A test that genuinely needs one asks for the
``allow_network`` marker, and there are none today.
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
def _no_network_anywhere(request, monkeypatch):
    """Refuse every outbound connection that is not loopback.

    Patched at ``socket.socket.connect`` rather than at boto3, deliberately.
    Patching the SDK would only prove this code does not call the SDK the way
    the test expects; patching the socket proves nothing reached the network by
    any route, including one somebody adds later.
    """
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
