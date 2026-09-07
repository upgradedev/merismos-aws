"""The swap test, on the path a stranger runs, as a test rather than an argument.

The sponsor persona's first kill criterion is one sentence: if removing the
sponsor's product leaves the demo working, the product is not the hero. It was
run properly on 2026-09-07, with a stub ``strands`` that imports cleanly and
raises the moment it is used, and **the whole demo path went green.** Fifty three
tests across the judge's journey and every screen a coordinator sees did not
notice that the SDK had gone.

The reason was not subtle once it was looked at. The offline path had no analyst
at all, so no ``Agent`` was ever constructed, and Strands was on the deployed
path and absent from the thirty second quickstart. The flagship claim was true
of the fleet and false of the thing a judge actually runs.

The fix was to give the offline path a real Strands agent over a scripted model,
which is what ``scripted.py`` had been written for and never wired to. These pin
it in both directions, because a one-sided proof of this is worth very little:

* with the SDK present, the demo path reaches the answers it always reached;
* with the SDK removed, it fails **at an assertion on the demo path**, not at
  import and not at collection. The persona names that distinction itself: a run
  that never reached the demo path has told nobody anything about the demo path.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from merismos.corpus import LocalCorpus
from merismos.fleet import new_run_id, run_chore, subject_for_offer
from merismos.ledger import InMemoryLedger, Thread

NETWORK = "kypseli-network"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.delenv("MERISMOS_MODEL", raising=False)


def _offer(offer_id: str) -> dict:
    return json.loads(LocalCorpus().read(f"offers/{offer_id}.json"))


def _chore(offer: dict, analyst):
    thread = Thread(
        ledger=InMemoryLedger(),
        subject=subject_for_offer(NETWORK, offer),
        run_id=new_run_id(),
    )
    return run_chore(LocalCorpus(), offer, thread, analyst=analyst, network=NETWORK)


# --------------------------------------------------------------------------
# With the SDK present.
# --------------------------------------------------------------------------


def test_the_offline_analyst_is_a_real_strands_agent_and_not_a_mock_of_one():
    """The type matters here. A mock would prove the test's expectations, not the SDK."""
    from strands import Agent
    from strands.models import Model

    from merismos.bedrock import scripted_analyst
    from merismos.tools import Toolbox

    analyst = scripted_analyst()
    agent = analyst.build_agent(Toolbox(corpus=LocalCorpus()), "brief")

    assert isinstance(agent, Agent)
    assert isinstance(agent.model, Model), (
        "the scripted planner is not a Strands model, so the agent loop is being "
        "stepped around rather than run"
    )
    assert agent.model.model_id == "scripted-planner/1.0.0"


def test_the_guard_on_the_offline_agent_refuses_a_real_call():
    """Asserted by watching it refuse rather than by asking a registry.

    The offline agent is built for whichever role it is given, so an evaluator is
    pointed at ``list_paths``, which the evaluator may not call. If the guard were
    not attached, the dispatcher would run the tool and the filing would be read
    by an identity that holds no read tool at all.
    """
    import asyncio

    from merismos.bedrock import scripted_analyst
    from merismos.tools import Toolbox

    analyst = scripted_analyst(role="evaluator")
    box = Toolbox(corpus=LocalCorpus())
    agent = analyst.build_agent(box, "brief")

    asyncio.run(agent.invoke_async("Look at the filing."))

    guard = next(h for h in [analyst._guard_seen] if h is not None)
    assert [r.tool for r in guard.refusals] == ["list_paths"], guard.refusals
    assert box.log.spent == 0, "a refused call still spent a read"


def test_an_offline_run_records_the_scripted_planner_and_never_a_bedrock_id():
    """A run recorded offline must not be mistakable for a run that called Bedrock."""
    from merismos.bedrock import scripted_analyst

    result = _chore(_offer("offer-4471"), scripted_analyst())

    models = {e.meta.get("model") for e in result.envelopes if e.meta}
    assert models == {"scripted-planner/1.0.0"}, models


@pytest.mark.parametrize(
    ("offer_id", "outcome"),
    [
        ("offer-4471", "awaiting_approval"),
        ("offer-4477", "blocked"),
        ("offer-4483", "awaiting_approval"),
    ],
)
def test_the_scripted_agent_reaches_the_same_answer_the_rules_alone_reach(
    offer_id, outcome
):
    """Wiring an agent in must not move the demo a judge watches.

    The scripted planner answers ``ok`` with no reason, and ``union`` never
    loosens, so the model envelope tightens nothing. If these ever diverge, the
    demo depends on which analyst happened to be configured, which is exactly the
    kind of thing this project refuses to leave implicit.
    """
    from merismos.bedrock import scripted_analyst

    assert _chore(_offer(offer_id), None).outcome == outcome
    assert _chore(_offer(offer_id), scripted_analyst()).outcome == outcome


def test_the_demo_a_stranger_runs_reaches_the_sdk_by_default():
    """`python -m merismos.demo`, with nothing set. The thirty second path."""
    from merismos.demo import main

    assert main(["--no-colour"]) == 0


def test_the_banner_says_which_of_the_three_paths_this_run_actually_took(capsys):
    """A banner that said "no model" while an agent ran would be the worst kind."""
    from merismos.demo import main

    main(["--no-colour"])
    screen = capsys.readouterr().out

    assert "scripted-planner/1.0.0" in screen
    assert "real Strands agents over a scripted model" in screen
    assert "no Bedrock" in screen
    assert "nothing here opens a socket" in screen


# --------------------------------------------------------------------------
# With the SDK removed. The half that decides whether any of the above matters.
# --------------------------------------------------------------------------


class SdkRemoved(RuntimeError):
    """What the stubbed SDK raises when anything reaches for it."""


@pytest.fixture
def strands_removed(monkeypatch):
    """A ``strands`` that imports cleanly and refuses the moment it is used.

    Importing cleanly is the point. The persona's third fail condition is a suite
    that goes red at import or collection instead of at an assertion, because a
    deleted module takes the run down before the journey executes and a run that
    never reached the demo path proves nothing about the demo path.
    """

    def refuse(*args, **kwargs):
        raise SdkRemoved("the Strands Agents SDK is not installed")

    strands = types.ModuleType("strands")
    strands.Agent = refuse
    strands.tool = refuse

    models = types.ModuleType("strands.models")
    models.BedrockModel = refuse

    class _Model:
        def __init__(self, *a, **k):
            refuse()

    models.Model = _Model

    hooks = types.ModuleType("strands.hooks")
    hooks.BeforeToolCallEvent = type("BeforeToolCallEvent", (), {})
    hooks.HookProvider = object
    hooks.HookRegistry = object

    strands.models = models
    strands.hooks = hooks

    for name, module in (
        ("strands", strands),
        ("strands.models", models),
        ("strands.hooks", hooks),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return strands


def test_with_the_sdk_removed_the_demo_path_fails_at_an_assertion(strands_removed):
    """The one that decides it. Same offer, same corpus, no SDK, and it stops.

    ``scripted_analyst`` is constructed and then used, which is where the stub
    refuses: inside the agent build, on the demo path, after collection and after
    the run has started. That is the failure the persona asks to be shown.
    """
    from merismos.bedrock import scripted_analyst

    with pytest.raises(SdkRemoved):
        from merismos.tools import Toolbox

        scripted_analyst().build_agent(Toolbox(corpus=LocalCorpus()), "brief")


def test_with_the_sdk_removed_a_chore_reports_it_rather_than_passing_quietly(
    strands_removed,
):
    """A run that cannot reach its analyst must not report a clean deterministic pass.

    ``run_chore`` turns an unreachable analyst into a finding, and the finding is
    what makes the removal visible in the record instead of invisible in the
    answer. Without this the swap test would go green on a fleet that had
    silently stopped using the product.
    """
    from merismos.bedrock import scripted_analyst

    result = _chore(_offer("offer-4471"), scripted_analyst())

    excuses = [
        f.detail
        for e in result.envelopes
        for f in e.findings
        if "model" in f.check or "model" in f.detail.lower()
    ]
    assert excuses, (
        "the SDK was removed and the run reported nothing about it. A chore that "
        "cannot reach its analyst and says so is the whole reason this is "
        "detectable at all"
    )
