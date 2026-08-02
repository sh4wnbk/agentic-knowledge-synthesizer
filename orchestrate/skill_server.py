"""
orchestrate/skill_server.py
Thin API surface for registering existing Python agents as Orchestrate skills.

User: Emergency manager / EOC supervisor reviewing incident reports.
Not a 911 call-taker tool — no citizen-facing audio or voice reassurance.
"""

import os
import requests as _requests
from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agents.data_bridge_agent import DataBridgeAgent
from agents.intake_agent import IntakeAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.overseer_agent import OverseerAgent
from agents.rag_knowledge_agent import RAGKnowledgeAgent
from agents.synthesis_agent import SynthesisAgent
from pipeline import run_pipeline
from agents.synthesis_agent import SynthesisUnavailable


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

# The complete set of statuses the incident-report endpoint can emit, declared
# in one place. The first three map from pipeline OutputStates; the last two are
# response-level failures raised (not returned) by the pipeline. Keeping all five
# here is what stops a consumer (the dashboard badge) from drifting out of sync
# with a status defined only as an inline literal.
STATE_LABELS = {
    "confirmed_delivery":       "CONFIRMED DELIVERY",
    "retry_corrected_delivery": "RETRY-CORRECTED DELIVERY",
    "honest_fallback":          "HONEST FALLBACK",
    "synthesis_unavailable":    "SYNTHESIS UNAVAILABLE",
    "pipeline_error":           "PIPELINE ERROR",
}


# ── Dashboard ─────────────────────────────────────────────────

@app.get("/")
@app.get("/about")
def dashboard():
    # Both routes serve the same single-page dashboard; the client picks the
    # console or the about view from location.pathname. One file, two real URLs,
    # so the explainer content has its own shareable link without duplicating the
    # header, token system, or theme controls. Firebase rewrites ** to Cloud Run,
    # so a direct hit or reload on /about reaches this handler.
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    return FileResponse(html_path, media_type="text/html")


# ── Health ────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ── GCP Cloud Run platform status proxy ───────────────────────

@app.get("/status/cloudrun")
def cloudrun_status() -> dict[str, Any]:
    """
    Proxies GCP's public incidents feed and filters for active Cloud Run
    incidents. Returns indicator + description without CORS issues.
    indicator values: "none" (all OK) | "minor" | "major" | "critical" | "unknown"
    """
    try:
        r = _requests.get(
            "https://status.cloud.google.com/incidents.json",
            timeout=5,
        )
        incidents = r.json()
        active = [
            i for i in incidents
            if not i.get("end") and any(
                "Cloud Run" in s.get("title", "") or "cloud-run" in s.get("id", "")
                for s in i.get("affected_products", [])
            )
        ]
        if active:
            severity  = active[0].get("severity", "medium").lower()
            indicator = "critical" if severity in ("high", "critical") else "minor"
            description = active[0].get("external_desc", "Cloud Run incident in progress")
        else:
            indicator   = "none"
            description = "All Systems Operational"
        return {
            "indicator":        indicator,
            "description":      description,
            "active_incidents": len(active),
            "url":              "https://status.cloud.google.com",
        }
    except Exception as exc:
        return {
            "indicator":        "unknown",
            "description":      str(exc),
            "active_incidents": 0,
            "url":              "https://status.cloud.google.com",
        }


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
    result         = run_pipeline(
        req.raw_input,
        intake=intake, orchestrator=orchestrator, rag=rag,
        bridge=bridge, overseer=overseer, synthesis=synthesis,
    )

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
    import traceback
    try:
        incident_id    = req.incident_id or str(uuid4())
        intent         = intake.parse(req.raw_input)
        cluster        = orchestrator.route(intent)
        agency_routing = orchestrator.get_agency_routing(cluster)
        citation_chain = orchestrator.get_citation_chain(cluster)
        result         = run_pipeline(
            req.raw_input,
            intake=intake, orchestrator=orchestrator, rag=rag,
            bridge=bridge, overseer=overseer, synthesis=synthesis,
        )
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
    except SynthesisUnavailable as exc:
        # Distinct from HONEST FALLBACK on purpose: the provider produced nothing,
        # so this is a plumbing failure, not a governed refusal. Say so plainly.
        print(f"[INCIDENT_REPORT] Synthesis unavailable: {exc}")
        return {
            "incident_id":   req.incident_id or "unknown",
            "output_status": STATE_LABELS["synthesis_unavailable"],
            "error":         str(exc),
            "detail":        ("The LLM provider returned no usable output. This is an "
                              "infrastructure failure, not an evidence-based fallback."),
        }
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[INCIDENT_REPORT] Unhandled exception:\n{tb}")
        return {
            "incident_id":   req.incident_id or "unknown",
            "output_status": STATE_LABELS["pipeline_error"],
            "error":         str(exc),
            "traceback":     tb,
        }
