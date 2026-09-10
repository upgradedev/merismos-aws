"""Explicit synthetic capacity disruption; original decisions remain in session history."""

import copy
import math

from .intake import as_document


def disrupt(state, offer, run, plan, body):
    if state["mode"] != "sandbox":
        raise ValueError("Disruption rehearsal is sandbox-only. Live evidence is not editable here.")
    if body.get("consent") is not True:
        raise ValueError("Confirm this simulated capacity change before recording it.")
    if run.get("replan_required"):
        raise ValueError("Replan the pending disruption before changing capacity again.")
    org, limit = body.get("org"), body.get("capacity")
    share = next((a for a in run.get("result", {}).get("draft_allocations", [])
                  if a["org"] == org), None)
    if not share or type(limit) not in (int, float) or not math.isfinite(limit) or not (
        0 <= limit < share["quantity"]
    ) or round(limit, 2) != limit:
        raise ValueError("Select an allocated organisation and a lower capacity, "
                         "zero or above, in the offer's unit with at most two decimals.")
    archived = {"offer": copy.deepcopy(offer), "run": copy.deepcopy(run),
                "plan": copy.deepcopy(plan)}
    state.setdefault("run_history", []).append(archived)
    state.setdefault("disruptions", {})[offer["id"]] = {
        "org": org, "capacity": limit, "unit": offer["unit"],
        "previous_quantity": share["quantity"], "before": copy.deepcopy(run["result"]),
        "before_digest": plan["digest"], "before_recorded": plan["recorded"],
        "before_key": plan["key"], "source": f"offers/{offer['id']}.json",
    }
    changed = {**offer, "dispatch_capacity_limits": {
        **offer.get("dispatch_capacity_limits", {}), org: limit}}
    state["files"][f"offers/{offer['id']}.json"] = as_document(changed)
    # The old result remains retrievable, but cannot authorize a stale pickup or approval.
    run["replan_required"] = True
