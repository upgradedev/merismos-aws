#!/usr/bin/env python
"""Take the Strands SDK away and prove the demo stops working.

Run it yourself, from the repository root, with no AWS account:

    python scripts/the_swap_test.py

**Why this is a script rather than only a test.** The claim it checks is the one
this entry rests on, and a claim of this kind should be runnable by somebody who
does not trust our test suite. It exits 0 when the journey goes red for the right
reason and 1 when it does not, so it can be read by a person and by CI.

**What it does.** It replaces ``strands`` with a module that imports cleanly and
raises the moment anything uses it, then runs the end to end journey a judge
watches. Importing cleanly is the whole trick. A deleted package takes the run
down at collection, and a run that never reached the demo path has told nobody
anything about the demo path.

**What it caught.** On 2026-09-07 this returned "the demo path does not need the
SDK" and it was right. The offline path had no analyst at all, so no ``Agent``
was ever constructed: the SDK was on the deployed fleet and absent from the
thirty second quickstart, which is the thing a judge actually runs. The offline
path now runs real Strands agents over a scripted model, and this script is what
stops that quietly reverting.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The journey a judge watches, and the screens a coordinator sees. If removing
#: the sponsor's product leaves either of these green, it is not load-bearing.
DEMO_PATH = (
    "tests/e2e/test_the_journey_a_judge_watches.py",
    "tests/integration/test_the_screens_a_coordinator_sees.py",
)

#: The assertion that must be the one that fails. Naming it is what stops this
#: script passing on a run that went red for an unrelated reason, which is the
#: way a check like this usually rots.
EXPECTED = "test_every_specialist_actually_reached_the_analyst"

POISON = '''
"""Installed ahead of merismos: a strands that imports and refuses when used."""
import sys, types


def _refuse(*args, **kwargs):
    raise RuntimeError("the Strands Agents SDK was removed for the swap test")


strands = types.ModuleType("strands")
strands.Agent = _refuse
strands.tool = _refuse

models = types.ModuleType("strands.models")
models.BedrockModel = _refuse


class _Model:
    def __init__(self, *a, **k):
        _refuse()


models.Model = _Model

hooks = types.ModuleType("strands.hooks")
hooks.BeforeToolCallEvent = type("BeforeToolCallEvent", (), {})
hooks.HookProvider = object
hooks.HookRegistry = object

strands.models = models
strands.hooks = hooks
sys.modules["strands"] = strands
sys.modules["strands.models"] = models
sys.modules["strands.hooks"] = hooks
'''


def main() -> int:
    sitecustomize = ROOT / "build" / "swap"
    sitecustomize.mkdir(parents=True, exist_ok=True)
    (sitecustomize / "sitecustomize.py").write_text(POISON, encoding="utf-8")

    env = {
        **{k: v for k, v in __import__("os").environ.items()},
        "PYTHONPATH": str(sitecustomize),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--no-cov", "-q", *DEMO_PATH],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    print(output)

    if proc.returncode == 0:
        print(
            textwrap.dedent(
                f"""
                SWAP TEST FAILED.

                The Strands SDK was removed and the demo path stayed green. The
                journey did not notice, so on the path a judge runs the SDK is
                not load-bearing. Expected {EXPECTED} to fail.
                """
            ).strip()
        )
        return 1

    if EXPECTED not in output:
        print(
            textwrap.dedent(
                f"""
                SWAP TEST INCONCLUSIVE.

                The run went red, but not at {EXPECTED}. A suite that dies at
                import or collection has told us nothing about the demo path.
                Read the output above before believing anything.
                """
            ).strip()
        )
        return 1

    print(
        textwrap.dedent(
            f"""
            SWAP TEST PASSED.

            With the SDK removed, the end to end journey fails at
            {EXPECTED}, on the demo path, after the run started. The demo says
            NOT REACHED on screen and the deterministic rules are what is left.
            """
        ).strip()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
