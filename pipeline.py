"""
pipeline.py
The six agents running in sequence.
This is the Slide 2 workflow in code.

Overseer monitors at three hooks.
Retry loop capped at MAX_RETRIES.
Beam search candidates evaluated by citation alignment.
Three output states — no fourth state exists.
"""

from agents.intake_agent        import IntakeAgent
from agents.orchestrator_agent  import OrchestratorAgent
from agents.rag_knowledge_agent import RAGKnowledgeAgent
from agents.data_bridge_agent   import DataBridgeAgent
from agents.overseer_agent      import OverseerAgent
from agents.synthesis_agent     import SynthesisAgent
from governance.output_states   import AgentOutput, OutputState
from config                     import MAX_RETRIES


def run_pipeline(raw_input: str, audio_path: str = None) -> AgentOutput:

    # ── Instantiate agents ────────────────────────────────────
    intake      = IntakeAgent()
    orchestrator = OrchestratorAgent()
    rag          = RAGKnowledgeAgent()
    bridge       = DataBridgeAgent()
    overseer     = OverseerAgent()
    synthesis    = SynthesisAgent()

    print("\n" + "═"*55)
    print("  AGENTIC KNOWLEDGE SYNTHESIZER — PIPELINE START")
    print("═"*55)

    # ── STEP 1: Transcribe audio if provided ──────────────────
    if audio_path:
        transcribed = intake.transcribe(audio_path)
        if transcribed:
            raw_input = transcribed
            print(f"[INTAKE] Transcribed: {raw_input[:80]}...")

    # ── STEP 2: Parse intent ──────────────────────────────────
    intent = intake.parse(raw_input)
    print(f"[INTAKE] Crisis type: {intent.get('crisis_type')} | "
          f"Complete: {intent.get('is_complete')}")

    # ── HOOK 1: Input Audit ───────────────────────────────────
    if not overseer.input_audit(intent):
        return AgentOutput(
            state          = OutputState.HONEST_FALLBACK,
            content        = ("Unable to structure your request. "
                              "Please describe your location and the nature "
                              "of the emergency."),
            citation       = None,
            confidence     = 0.0,
            citation_score = 0.0,
            audit_log      = overseer.get_audit_log()
        )

    # ── STEP 3: Route to cluster ──────────────────────────────
    cluster = orchestrator.route(intent)
    query   = orchestrator.build_query(intent, cluster)
    bbox    = orchestrator.get_bbox(cluster)

    # ── STEP 4: Retrieve — fires before reasoning ─────────────
    retrieval      = rag.retrieve(query)
    retrieval_retry = 0

    # ── HOOK 2: Retrieval Audit ───────────────────────────────
    while not overseer.retrieval_audit(retrieval):
        if retrieval_retry >= MAX_RETRIES:
            return AgentOutput(
                state          = OutputState.HONEST_FALLBACK,
                content        = (
                    "Partial context available. Seismic and vulnerability "
                    "data could not be retrieved with sufficient confidence. "
                    f"Sources attempted: {retrieval.get('citation', 'none')}. "
                    "Please contact local emergency services directly."
                ),
                citation       = retrieval.get("citation"),
                confidence     = retrieval.get("confidence", 0.0),
                citation_score = 0.0,
                audit_log      = overseer.get_audit_log()
            )
        retrieval_retry += 1
        print(f"[PIPELINE] Retrieval retry {retrieval_retry}/{MAX_RETRIES}")
        retrieval = rag.retrieve(query)

    # ── STEP 5: Fetch from data bridge ────────────────────────
    bridge_data = bridge.fetch(intent, retrieval, bbox)

    # ── STEP 6: Generate beam candidates ─────────────────────
    candidates = synthesis.generate_candidates(intent, retrieval, bridge_data)

    if not candidates:
        return AgentOutput(
            state          = OutputState.HONEST_FALLBACK,
            content        = "Generation failed. Please contact emergency services directly.",
            citation       = retrieval.get("citation"),
            confidence     = retrieval.get("confidence", 0.0),
            citation_score = 0.0,
            audit_log      = overseer.get_audit_log()
        )

    # ── HOOK 3: Pre-Delivery Check ────────────────────────────
    # Evaluate each beam candidate by citation alignment score.
    # Select the highest-scoring candidate — not the highest
    # probability token sequence. This is the architectural
    # correction for greedy decoding.
    citation          = retrieval.get("citation")
    delivery_retries  = 0
    first_pass        = True
    best_output       = None
    best_score        = 0.0

    while True:
        # Score all candidates, select best
        for candidate in candidates:
            passed, score = overseer.pre_delivery_check(candidate, citation)
            if score > best_score:
                best_score  = score
                best_output = candidate

        if best_output and best_score >= 0.0:
            # At least one candidate passed or is best available
            passed, _ = overseer.pre_delivery_check(best_output, citation)
            if passed:
                break

        if delivery_retries >= MAX_RETRIES:
            # Retry budget exhausted — honest fallback
            fallback_content = (
                f"Partial validated context (confidence: "
                f"{retrieval.get('confidence', 0):.2f}): "
                f"{best_output[:300] if best_output else 'No output generated.'}"
                f"\nSource: {citation or 'unavailable'}."
            )
            return AgentOutput(
                state          = OutputState.HONEST_FALLBACK,
                content        = fallback_content,
                citation       = citation,
                confidence     = retrieval.get("confidence", 0.0),
                citation_score = best_score,
                audit_log      = overseer.get_audit_log()
            )

        # Retry with fresh retrieval and new candidates
        delivery_retries += 1
        first_pass        = False
        print(f"[PIPELINE] Delivery retry {delivery_retries}/{MAX_RETRIES} "
              f"— re-retrieving with amended context")
        retrieval   = rag.retrieve(query)
        bridge_data = bridge.fetch(intent, retrieval, bbox)
        candidates  = synthesis.generate_candidates(intent, retrieval, bridge_data)
        citation    = retrieval.get("citation")
        best_output = None
        best_score  = 0.0

    # ── Deliver ───────────────────────────────────────────────
    state = (
        OutputState.CONFIRMED_DELIVERY if first_pass
        else OutputState.RETRY_CORRECTED_DELIVERY
    )

    return AgentOutput(
        state          = state,
        content        = best_output,
        citation       = citation,
        confidence     = retrieval.get("confidence", 0.0),
        citation_score = best_score,
        audit_log      = overseer.get_audit_log()
    )
