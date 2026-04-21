"""
orchestrate/skill_server.py
Thin API surface for registering existing Python agents as Orchestrate skills.

User: Emergency manager / EOC supervisor reviewing incident reports.
Not a 911 call-taker tool — no citizen-facing audio or voice reassurance.
"""

from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agents.data_bridge_agent import DataBridgeAgent
from agents.intake_agent import IntakeAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.overseer_agent import OverseerAgent
from agents.rag_knowledge_agent import RAGKnowledgeAgent
from agents.synthesis_agent import SynthesisAgent
from pipeline import run_pipeline


app = FastAPI(title="AEGIS — Incident Routing Skill Bridge", version="0.2.0")

intake       = IntakeAgent()
orchestrator = OrchestratorAgent()
rag          = RAGKnowledgeAgent()
bridge       = DataBridgeAgent()
overseer     = OverseerAgent()
synthesis    = SynthesisAgent()


# ── Request models ────────────────────────────────────────────

class IntentRouteRequest(BaseModel):
    raw_input: str = Field(..., description="Incident report text")


class RetrieveRequest(BaseModel):
    query: str = Field(..., description="Semantic query text")


class BridgeRequest(BaseModel):
    intent: dict[str, Any]
    retrieval: dict[str, Any]
    bbox: Optional[dict[str, Any]] = None
    agency_routing: Optional[dict[str, Any]] = None


class SynthesisRequest(BaseModel):
    intent: dict[str, Any]
    retrieval: dict[str, Any]
    bridge: dict[str, Any]


class GovernanceRequest(BaseModel):
    output: str
    citation: str


class PipelineRequest(BaseModel):
    raw_input: str


class IncidentReportRequest(BaseModel):
    raw_input: str
    incident_id: Optional[str] = None
    channel: Optional[str] = Field(default="text", description="text|api")


# ── State label map (shared) ──────────────────────────────────

STATE_LABELS = {
    "confirmed_delivery":       "CONFIRMED DELIVERY",
    "retry_corrected_delivery": "RETRY-CORRECTED DELIVERY",
    "honest_fallback":          "HONEST FALLBACK",
}


# ── Health ────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Skill endpoints (individual agents) ──────────────────────

@app.post("/skills/intent-route")
def intent_route(req: IntentRouteRequest) -> dict[str, Any]:
    intent         = intake.parse(req.raw_input)
    cluster        = orchestrator.route(intent)
    query          = orchestrator.build_query(intent, cluster)
    bbox           = orchestrator.get_bbox(cluster)
    agency_routing = orchestrator.get_agency_routing(cluster)
    citation_chain = orchestrator.get_citation_chain(cluster)
    return {
        "intent":         intent,
        "cluster":        cluster,
        "query":          query,
        "bbox":           bbox,
        "agency_routing": agency_routing,
        "citation_chain": citation_chain,
    }


@app.post("/skills/retrieve")
def retrieve(req: RetrieveRequest) -> dict[str, Any]:
    return rag.retrieve(req.query)


@app.post("/skills/bridge")
def fetch_bridge(req: BridgeRequest) -> dict[str, Any]:
    agency_routing = req.agency_routing
    if agency_routing is None:
        cluster        = orchestrator.route(req.intent)
        agency_routing = orchestrator.get_agency_routing(cluster)
    return bridge.fetch(req.intent, req.retrieval, req.bbox, agency_routing)


@app.post("/skills/synthesize")
def synthesize(req: SynthesisRequest) -> dict[str, Any]:
    candidates = synthesis.generate_candidates(req.intent, req.retrieval, req.bridge)
    return {"candidates": candidates}


@app.post("/skills/governance/pre-delivery")
def pre_delivery(req: GovernanceRequest) -> dict[str, Any]:
    passed, score = overseer.pre_delivery_check(req.output, req.citation)
    return {"passed": passed, "citation_score": score}


# ── Workflow endpoints ────────────────────────────────────────

@app.post("/workflow/crisis-brief")
def crisis_brief(req: PipelineRequest) -> dict[str, Any]:
    intent         = intake.parse(req.raw_input)
    cluster        = orchestrator.route(intent)
    agency_routing = orchestrator.get_agency_routing(cluster)
    citation_chain = orchestrator.get_citation_chain(cluster)
    result         = run_pipeline(req.raw_input)

    return {
        "output_status":        STATE_LABELS.get(result.state.value, result.state.value),
        "citation_alignment":   f"{result.citation_score:.1%}",
        "retrieval_confidence": f"{result.confidence:.1%}",
        "brief":                result.content,
        "citation":             result.citation,
        "cluster":              cluster,
        "agency_routing_baseline": agency_routing,
        "citation_chain":       citation_chain,
        "audit_log":            result.audit_log,
    }


@app.post("/workflow/incident-report")
def incident_report(req: IncidentReportRequest) -> dict[str, Any]:
    """
    Primary EOC endpoint. Accepts an incident report from an emergency manager
    and returns a validated inter-agency routing brief.
    """
    incident_id    = req.incident_id or str(uuid4())
    intent         = intake.parse(req.raw_input)
    cluster        = orchestrator.route(intent)
    agency_routing = orchestrator.get_agency_routing(cluster)
    citation_chain = orchestrator.get_citation_chain(cluster)
    result         = run_pipeline(req.raw_input)
    status_label   = STATE_LABELS.get(result.state.value, result.state.value)

    return {
        "incident_id":          incident_id,
        "output_status":        status_label,
        "citation_alignment":   f"{result.citation_score:.1%}",
        "retrieval_confidence": f"{result.confidence:.1%}",
        "brief":                result.content,
        "citation":             result.citation,
        "cluster":              cluster,
        "agency_routing_baseline": agency_routing,
        "citation_chain":       citation_chain,
        "audit_log":            result.audit_log,
    }
