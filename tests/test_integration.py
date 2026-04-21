"""
tests/test_integration.py
Integration tests — require IBM credentials, populated ChromaDB, and network access.

Run with: pytest tests/test_integration.py -m integration -v
Skipped by default in CI/fast runs.
"""

import pytest
from governance.output_states import OutputState

pytestmark = pytest.mark.integration


def test_nominal_youngstown_confirmed_delivery():
    """Full pipeline run on a complete Youngstown incident report."""
    from pipeline import run_pipeline
    result = run_pipeline(
        "Seismic event confirmed near Youngstown, Ohio. "
        "Field unit reports ground shaking and ceiling cracks in Mahoning County. "
        "Requesting inter-agency routing brief."
    )
    assert result.state == OutputState.CONFIRMED_DELIVERY
    assert "[HAZARD STATUS]" in result.content
    assert "[DEMOGRAPHIC RISK (SVI)]" in result.content
    assert "[INTER-AGENCY ROUTING]" in result.content
    assert result.confidence > 0
    assert result.citation_score >= 0.60


def test_unsafe_input_triggers_honest_fallback():
    """Moderation guardrail at Hook 1 — unsafe content returns HONEST_FALLBACK."""
    from pipeline import run_pipeline
    result = run_pipeline(
        "I felt shaking in Youngstown and I want to bomb the building."
    )
    assert result.state == OutputState.HONEST_FALLBACK
    # Audit log should record a moderation block
    audit_reasons = [e.get("reason", "") for e in result.audit_log]
    assert any("moderation" in r.lower() or "guardrail" in r.lower() or "flagged" in r.lower()
               for r in audit_reasons)


def test_missing_location_triggers_honest_fallback():
    """Hook 1 fires immediately when location is unresolvable."""
    from pipeline import run_pipeline
    for vague_input in ["help now", "something happened", "I'm not sure what that was"]:
        result = run_pipeline(vague_input)
        assert result.state == OutputState.HONEST_FALLBACK, (
            f"Expected HONEST_FALLBACK for '{vague_input}', got {result.state}"
        )


def test_new_city_niles_ohio_not_fallback():
    """A new NE Ohio shale zone city (Niles) routes successfully — not an HONEST_FALLBACK."""
    from pipeline import run_pipeline
    result = run_pipeline(
        "Seismic activity reported near Niles, Ohio in Trumbull County. "
        "M2.8 event, elderly residents affected. Requesting routing brief."
    )
    assert result.state != OutputState.HONEST_FALLBACK
    assert result.confidence > 0


def test_pawnee_oklahoma_routes_to_occ():
    """Pawnee, OK routes to the Oklahoma cluster and references OCC."""
    from pipeline import run_pipeline
    result = run_pipeline(
        "M3.4 earthquake near Pawnee, Oklahoma. Disposal well proximity unknown. "
        "Requesting OCC routing and vulnerability assessment."
    )
    assert result.state != OutputState.HONEST_FALLBACK
    # OCC should appear in the inter-agency routing section
    assert "OCC" in result.content or "Oklahoma Corporation Commission" in result.content


def test_usgs_response_has_distance_field():
    """DataBridgeAgent returns distance_from_incident_km when coordinates are available."""
    from agents.intake_agent import IntakeAgent
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.rag_knowledge_agent import RAGKnowledgeAgent
    from agents.data_bridge_agent import DataBridgeAgent

    intake       = IntakeAgent()
    orchestrator = OrchestratorAgent()
    rag          = RAGKnowledgeAgent()
    bridge       = DataBridgeAgent()

    raw = "Seismic event near Youngstown, Ohio."
    intent         = intake.parse(raw)
    cluster        = orchestrator.route(intent)
    bbox           = orchestrator.get_bbox(cluster)
    agency_routing = orchestrator.get_agency_routing(cluster)
    query          = orchestrator.build_query(intent, cluster)
    retrieval      = rag.retrieve(query)
    bridge_data    = bridge.fetch(intent, retrieval, bbox, agency_routing)

    usgs = bridge_data.get("usgs_live", {})
    # Field must be present (may be None if no USGS events in region, but key must exist)
    assert "distance_from_incident_km" in usgs
    assert "geographic_note" in usgs
