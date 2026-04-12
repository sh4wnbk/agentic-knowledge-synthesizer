"""
orchestrate/skill_server.py
Thin API surface for registering existing Python agents as Orchestrate skills.
"""

from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agents.data_bridge_agent import DataBridgeAgent
from agents.intake_agent import IntakeAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.overseer_agent import OverseerAgent
from agents.rag_knowledge_agent import RAGKnowledgeAgent
from agents.synthesis_agent import SynthesisAgent
from pipeline import run_pipeline


app = FastAPI(title="Agentic Knowledge Synthesizer Skill Bridge", version="0.1.0")

intake = IntakeAgent()
orchestrator = OrchestratorAgent()
rag = RAGKnowledgeAgent()
bridge = DataBridgeAgent()
overseer = OverseerAgent()
synthesis = SynthesisAgent()


class IntentRouteRequest(BaseModel):
    raw_input: str = Field(..., description="Citizen/dispatcher input text")


class RetrieveRequest(BaseModel):
    query: str = Field(..., description="Semantic query text")


class BridgeRequest(BaseModel):
    intent: dict[str, Any]
    retrieval: dict[str, Any]
    bbox: Optional[dict[str, Any]] = None


class SynthesisRequest(BaseModel):
    intent: dict[str, Any]
    retrieval: dict[str, Any]
    bridge: dict[str, Any]


class GovernanceRequest(BaseModel):
    output: str
    citation: str


class PipelineRequest(BaseModel):
    raw_input: str
    audio_path: Optional[str] = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/skills/intent-route")
def intent_route(req: IntentRouteRequest) -> dict[str, Any]:
    intent = intake.parse(req.raw_input)
    cluster = orchestrator.route(intent)
    query = orchestrator.build_query(intent, cluster)
    bbox = orchestrator.get_bbox(cluster)
    return {
        "intent": intent,
        "cluster": cluster,
        "query": query,
        "bbox": bbox,
    }


@app.post("/skills/retrieve")
def retrieve(req: RetrieveRequest) -> dict[str, Any]:
    return rag.retrieve(req.query)


@app.post("/skills/bridge")
def fetch_bridge(req: BridgeRequest) -> dict[str, Any]:
    return bridge.fetch(req.intent, req.retrieval, req.bbox)


@app.post("/skills/synthesize")
def synthesize(req: SynthesisRequest) -> dict[str, Any]:
    candidates = synthesis.generate_candidates(req.intent, req.retrieval, req.bridge)
    return {"candidates": candidates}


@app.post("/skills/governance/pre-delivery")
def pre_delivery(req: GovernanceRequest) -> dict[str, Any]:
    passed, score = overseer.pre_delivery_check(req.output, req.citation)
    return {"passed": passed, "citation_score": score}


@app.post("/workflow/crisis-brief")
def crisis_brief(req: PipelineRequest) -> dict[str, Any]:
    result = run_pipeline(req.raw_input, req.audio_path)

    state_labels = {
        "confirmed_delivery":       "CONFIRMED DELIVERY",
        "retry_corrected_delivery": "RETRY-CORRECTED DELIVERY",
        "honest_fallback":          "HONEST FALLBACK",
    }

    return {
        "output_status":       state_labels.get(result.state.value, result.state.value),
        "citation_alignment":  f"{result.citation_score:.1%}",
        "retrieval_confidence": f"{result.confidence:.1%}",
        "brief":               result.content,
        "citation":            result.citation,
        "audit_log":           result.audit_log,
    }