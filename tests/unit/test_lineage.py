"""Unit tests for Merismos cryptographic food donation lineage and provenance graph."""

from merismos.lineage import LineageNode, LineageStage, ProvenanceChain


def test_empty_chain():
    chain = ProvenanceChain(offer_id="OFFER-991")
    assert chain.offer_id == "OFFER-991"
    assert chain.nodes == ()
    valid, msg = chain.verify_integrity()
    assert valid is True
    assert "empty" in msg


def test_append_stages_and_verify_integrity():
    chain = ProvenanceChain(offer_id="OFFER-2026-4481")

    # Stage 1: Donor offer
    n1 = chain.append_stage(
        stage=LineageStage.DONOR_OFFER,
        actor="donor:supermarket-central",
        data={"category": "dairy", "quantity_kg": 250.0, "best_before": "2026-09-08"},
        timestamp=1725440000.0,
    )
    assert isinstance(n1, LineageNode)
    assert n1.parent_hash == "0" * 64

    # Stage 2: Food safety inspection
    n2 = chain.append_stage(
        stage=LineageStage.SAFETY_INSPECTION,
        actor="specialist:food-safety",
        data={"temp_celsius": 3.4, "status": "approved"},
        timestamp=1725440300.0,
    )
    assert n2.parent_hash == n1.node_hash

    # Stage 3: OR solver optimization
    n3 = chain.append_stage(
        stage=LineageStage.OR_OPTIMIZATION,
        actor="solver:combinatorial",
        data={"shares_allocated": 3, "max_ratio": 0.40},
        timestamp=1725440600.0,
    )
    assert n3.parent_hash == n2.node_hash

    # Stage 4: Human approval
    n4 = chain.append_stage(
        stage=LineageStage.HUMAN_APPROVAL,
        actor="coordinator:maria-p",
        data={"approval_signature": "APPROVED-2026-09-04"},
        timestamp=1725440900.0,
    )
    assert n4.parent_hash == n3.node_hash
    assert chain.head_hash == n4.node_hash

    # Integrity verification
    valid, msg = chain.verify_integrity()
    assert valid is True
    assert "Integrity verified across 4 custody stages" in msg


def test_tampered_node_hash_detected():
    chain = ProvenanceChain(offer_id="OFFER-TAMPER")
    chain.append_stage(LineageStage.DONOR_OFFER, "donor", "fresh bread", timestamp=1000.0)
    chain.append_stage(LineageStage.SAFETY_INSPECTION, "inspector", "temp ok", timestamp=2000.0)

    # Tamper with internal node
    tampered_node = LineageNode(
        stage=chain.nodes[0].stage,
        offer_id=chain.nodes[0].offer_id,
        actor=chain.nodes[0].actor,
        data_summary="poisoned bread",
        parent_hash=chain.nodes[0].parent_hash,
        payload_hash="fakehash",
        node_hash="corruptedhash",
        timestamp=chain.nodes[0].timestamp,
    )
    chain._nodes[0] = tampered_node

    valid, msg = chain.verify_integrity()
    assert valid is False
    assert "Tampered hash at node 0" in msg


def test_broken_parent_link_detected():
    chain = ProvenanceChain(offer_id="OFFER-BROKEN")
    chain.append_stage(LineageStage.DONOR_OFFER, "donor", "data1", timestamp=1000.0)
    chain.append_stage(LineageStage.SAFETY_INSPECTION, "inspector", "data2", timestamp=2000.0)

    # Tamper with parent hash of node 1
    tampered_node1 = LineageNode(
        stage=chain.nodes[1].stage,
        offer_id=chain.nodes[1].offer_id,
        actor=chain.nodes[1].actor,
        data_summary=chain.nodes[1].data_summary,
        parent_hash="invalid_parent_hash",
        payload_hash=chain.nodes[1].payload_hash,
        node_hash=chain.nodes[1].node_hash,
        timestamp=chain.nodes[1].timestamp,
    )
    chain._nodes[1] = tampered_node1

    valid, msg = chain.verify_integrity()
    assert valid is False
    assert "Broken link at node 1" in msg


def test_export_dag():
    chain = ProvenanceChain(offer_id="OFFER-DAG")
    chain.append_stage(LineageStage.DONOR_OFFER, "donor", "lot 101", timestamp=1000.0)
    chain.append_stage(LineageStage.SAFETY_INSPECTION, "safety", "passed", timestamp=1100.0)
    chain.append_stage(LineageStage.HUMAN_APPROVAL, "lead", "signed", timestamp=1200.0)

    dag = chain.export_dag()
    assert dag["offer_id"] == "OFFER-DAG"
    assert dag["total_stages"] == 3
    assert len(dag["nodes"]) == 3
    assert len(dag["edges"]) == 2
    assert dag["edges"][0]["transition"] == "donor_offer -> safety_inspection"

    n_dict = chain.nodes[0].as_dict()
    assert n_dict["stage"] == "donor_offer"
    assert n_dict["actor"] == "donor"
