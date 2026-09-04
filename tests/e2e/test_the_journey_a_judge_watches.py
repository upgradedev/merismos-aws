"""The demo, driven exactly the way the README says to run it.

If the README's command changes and this does not, one of the two is wrong and
this test is where that shows. It asserts the things a viewer actually reads off
the screen, including the honesty banner, because a demo that quietly took the
offline path while looking like the deployed one is the failure this whole file
exists to prevent.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from merismos.demo import main


@pytest.fixture
def screen(capsys) -> str:
    assert main(["--no-colour"]) == 0
    return capsys.readouterr().out


def test_the_first_thing_on_screen_is_which_path_this_run_took(screen):
    head = screen.splitlines()[:10]

    assert any("ledger" in line and "memory" in line for line in head)
    assert any("model" in line for line in head)
    assert any("scheduler" in line for line in head)


def test_the_offline_path_announces_itself(screen):
    """Otherwise a stub looks exactly like the deployed system."""
    assert "OFFLINE PATH" in screen
    assert "No AWS account is in use" in screen
    assert "no model is consulted" in screen


def test_every_offer_in_the_corpus_reaches_an_outcome(screen):
    for offer_id in ("offer-4471", "offer-4477", "offer-4483"):
        assert offer_id in screen


def test_the_broken_cold_chain_is_refused_in_full_and_says_why(screen):
    assert "blocked" in screen
    assert "cold chain was broken for 6 hours" in screen
    assert "refused in full, not reduced" in screen


def test_a_passing_offer_stops_at_a_person_and_publishes_nothing(screen):
    assert "awaiting_approval" in screen
    assert "A person has to read the bytes" in screen
    assert "Nothing above published anything" in screen


def test_the_screen_names_who_is_not_receiving_a_share(screen):
    """A decision nobody can see is a decision that gets re-litigated by phone."""
    assert "not receiving" in screen
    assert "Elpida Night Shelter" in screen


def test_the_comparison_that_settles_it_runs_live_rather_than_being_quoted(screen):
    """A viewer sees both answers, rather than being told what they would be."""
    assert "declared fields only" in screen
    assert "after reading the manifest" in screen
    assert "excluded   nobody" in screen
    assert "ships alcohol to a recovery shelter and a school" in screen


def test_the_reads_each_run_made_are_shown(screen):
    """The agency is inspectable, so the files it opened are on the screen."""
    assert "opened" in screen
    assert "offers/manifests/4483.md" in screen


def test_the_demo_runs_as_a_module_the_way_the_readme_says():
    """The README's exact command, executed. A quickstart nobody ran is a guess."""
    completed = subprocess.run(
        [sys.executable, "-m", "merismos.demo", "--no-colour"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert "MERISMOS" in completed.stdout
    assert "OFFLINE PATH" in completed.stdout


def test_asking_for_a_model_by_name_is_what_turns_one_on():
    """The offline path is the default, and the deployed path is opted into.

    Asserted without a network call: the analyst is only constructed when the
    variable is set, so an unset environment cannot silently reach Bedrock.
    """
    from merismos.bedrock import analyst_from_env

    assert analyst_from_env({"MERISMOS_MODEL": "none"}) is None
    assert analyst_from_env({"MERISMOS_MODEL": "eu.anthropic.claude-opus-5"}) is not None
