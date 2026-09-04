"""Unit tests for the combinatorial allocation solver."""

from merismos.solver import (
    AllocationSolution,
    PantryShare,
    solve_allocation,
    verify_constraints,
)


def test_solve_empty_or_zero():
    sol = solve_allocation(0.0, ["pantry-a", "pantry-b"])
    assert sol.total_allocated == 0.0
    assert sol.shares == ()
    assert sol.is_feasible is True

    sol_no_orgs = solve_allocation(100.0, [])
    assert sol_no_orgs.total_allocated == 0.0
    assert sol_no_orgs.unallocated_remainder == 100.0


def test_solve_allocation_respects_40_percent_ceiling():
    # 100 kg split between 2 pantries. 40% cap = 40 kg max per pantry.
    # Total allocated should be 80 kg, with 20 kg unallocated remainder.
    sol = solve_allocation(100.0, ["pantry-a", "pantry-b"], max_quota_ratio=0.40)
    assert isinstance(sol, AllocationSolution)
    assert sol.total_offered == 100.0
    assert sol.total_allocated == 80.0
    assert sol.unallocated_remainder == 20.0
    assert len(sol.shares) == 2
    for s in sol.shares:
        assert isinstance(s, PantryShare)
        assert s.quantity <= 40.0
        assert s.percentage <= 40.0
    assert sol.is_feasible is True
    assert sol.proof["quota_satisfied"] is True


def test_solve_allocation_three_pantries_distributes_all():
    # 3 pantries with 100 kg.
    # Under 40% cap, max is 40 kg each. 3 * 33.33 = 100 kg total.
    sol = solve_allocation(100.0, ["pantry-a", "pantry-b", "pantry-c"], max_quota_ratio=0.40)
    assert sol.is_feasible is True
    assert sol.total_allocated == 100.0
    assert sol.unallocated_remainder == 0.0
    for s in sol.shares:
        assert s.quantity <= 40.0


def test_solve_allocation_respects_capacity_limits():
    # 100 kg across 3 pantries, but pantry-a only has 10 kg capacity
    capacities = {"pantry-a": 10.0, "pantry-b": 50.0, "pantry-c": 50.0}
    sol = solve_allocation(
        100.0,
        ["pantry-a", "pantry-b", "pantry-c"],
        max_quota_ratio=0.40,
        capacities=capacities,
    )
    assert sol.is_feasible is True
    shares = {s.org: s.quantity for s in sol.shares}
    assert shares["pantry-a"] <= 10.0
    assert shares["pantry-b"] <= 40.0
    assert shares["pantry-c"] <= 40.0
    assert sol.total_allocated == 90.0  # 10 + 40 + 40 = 90
    assert sol.unallocated_remainder == 10.0


def test_verify_constraints_passes_valid():
    allocations = [
        {"org": "pantry-a", "quantity": 30.0},
        {"org": "pantry-b", "quantity": 35.0},
        {"org": "pantry-c", "quantity": 35.0},
    ]
    valid, violations = verify_constraints(allocations, total_quantity=100.0, max_quota_ratio=0.40)
    assert valid is True
    assert violations == []


def test_verify_constraints_detects_ceiling_violation():
    allocations = [
        {"org": "pantry-a", "quantity": 55.0},  # Exceeds 40.0
        {"org": "pantry-b", "quantity": 35.0},
    ]
    valid, violations = verify_constraints(allocations, total_quantity=100.0, max_quota_ratio=0.40)
    assert valid is False
    assert any("exceeding 40% ceiling" in v for v in violations)


def test_verify_constraints_detects_barred_org():
    allocations = [
        {"org": "pantry-a", "quantity": 30.0},
        {"org": "pantry-b", "quantity": 30.0},
    ]
    valid, violations = verify_constraints(
        allocations,
        total_quantity=100.0,
        max_quota_ratio=0.40,
        barred_orgs={"pantry-b"},
    )
    assert valid is False
    assert any("barred organization 'pantry-b'" in v for v in violations)


def test_verify_constraints_detects_over_allocation():
    allocations = [
        {"org": "pantry-a", "quantity": 35.0},
        {"org": "pantry-b", "quantity": 35.0},
        {"org": "pantry-c", "quantity": 35.0},  # Total = 105 > 100
    ]
    valid, violations = verify_constraints(allocations, total_quantity=100.0, max_quota_ratio=0.40)
    assert valid is False
    assert any("exceeds offered quantity" in v for v in violations)


def test_verify_constraints_detects_negative_allocation():
    allocations = [{"org": "pantry-a", "quantity": -5.0}]
    valid, violations = verify_constraints(allocations, total_quantity=100.0)
    assert valid is False
    assert any("Negative allocation" in v for v in violations)
