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


def run_pipeline(raw_input: str) -> AgentOutput:

    # ── Instantiate agents ────────────────────────────────────
    intake      = IntakeAgent()
    orchestrator = OrchestratorAgent()
    rag          = RAGKnowledgeAgent()
    bridge       = DataBridgeAgent()
    overseer     = OverseerAgent()
    synthesis    = SynthesisAgent()

    print("\n" + "═"*55)
    print("  AEGIS — INCIDENT ROUTING PIPELINE START")
    print("═"*55)

    # ── STEP 1: Parse intent ──────────────────────────────────
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
    agency_routing = orchestrator.get_agency_routing(cluster)
    citation_chain = orchestrator.get_citation_chain(cluster)

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
    bridge_data = bridge.fetch(intent, retrieval, bbox, agency_routing)

    # Promote the citation chain into the retrieval record so downstream
    # generation and governance see the same provenance string.
    retrieval["citation"] = citation_chain

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
    context           = retrieval.get("context", "")
    delivery_retries  = 0
    first_pass        = True
    best_output       = None
    best_score        = -1.0

    while True:
        # Score all candidates by semantic alignment with retrieved context.
        # Select the highest-scoring beam — not highest token probability.
        # Each candidate is checked exactly once; no re-check of the winner.
        best_passed = False
        for candidate in candidates:
            passed, score = overseer.pre_delivery_check(candidate, citation, context)
            if score > best_score:
                best_score  = score
                best_output = candidate
                best_passed = passed

        if best_output and best_passed:
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
        bridge_data = bridge.fetch(intent, retrieval, bbox, agency_routing)
        candidates  = synthesis.generate_candidates(intent, retrieval, bridge_data)
        citation    = retrieval.get("citation")
        context     = retrieval.get("context", "")
        best_output = None
        best_score  = -1.0

    # ── Replace [INTER-AGENCY ROUTING] with deterministic table ──
    # The LLM reliably truncates table rows. Generate from bridge data
    # directly so every agency appears and tier promotion is reflected.
    # Injected after Overseer scoring so it does not affect citation alignment.
    agency_brief = bridge_data.get("agency_routing", {})
    if agency_brief and any(
        agency_brief.get(k) for k in ("tier_1_immediate", "tier_2_within_hour", "tier_3_as_warranted")
    ):
        table_rows = ["| Tier | Agency | Role |", "|---|---|---|"]
        for agency in agency_brief.get("tier_1_immediate", []):
            role = agency.get("role", "")
            table_rows.append(f"| 1 — IMMEDIATE | {agency['name']} | {role} |")
        for agency in agency_brief.get("tier_2_within_hour", []):
            role = agency.get("role", "")
            table_rows.append(f"| 2 — WITHIN HOUR | {agency['name']} | {role} |")
        for agency in agency_brief.get("tier_3_as_warranted", []):
            role = agency.get("role", "")
            if agency.get("hotline"):
                role += f" · {agency['hotline']}"
            table_rows.append(f"| 3 — AS WARRANTED | {agency['name']} | {role} |")
        routing_table = "\n".join(table_rows)

        # Strip whatever the LLM generated for [INTER-AGENCY ROUTING] and replace it
        import re as _re
        best_output = _re.sub(
            r"\*?\*?\[INTER-AGENCY ROUTING\]\*?\*?.*",
            f"**[INTER-AGENCY ROUTING]**\n{routing_table}",
            best_output,
            flags=_re.DOTALL
        )

    # ── Append verification links ─────────────────────────────
    # Links are constructed from deterministic API data — not LLM-generated.
    # Appended after Overseer scoring so they don't affect citation alignment.
    verification_lines = []
    usgs = bridge_data.get("usgs_live", {})
    svi  = bridge_data.get("svi_lookup", {})
    external_ops = bridge_data.get("external_operational_picture", {})

    usgs_url = usgs.get("verification_url")
    svi_url  = svi.get("verification_url")

    if usgs_url:
        verification_lines.append(f"[USGS Event]({usgs_url})")
    else:
        verification_lines.append("[USGS Earthquake Map](https://earthquake.usgs.gov/earthquakes/map/)")

    if svi_url and svi.get("tract_geoid"):
        verification_lines.append(
            f"[Census Tract {svi['tract_geoid']} — Census Bureau]({svi_url})"
        )
    else:
        verification_lines.append("[CDC/ATSDR Social Vulnerability Index](https://www.atsdr.cdc.gov/placeandhealth/svi/index.html)")

    # External source verification links (FEMA + IFRC)
    source_urls = external_ops.get("source_validation_urls", {})
    fema_portal = source_urls.get("fema_portal")
    ifrc_portal = source_urls.get("ifrc_portal")

    if fema_portal:
        verification_lines.append(f"[FEMA Declarations (Portal)]({fema_portal})")
    if ifrc_portal:
        verification_lines.append(f"[IFRC Emergencies (Portal)]({ifrc_portal})")

    for evt in external_ops.get("top_events", [])[:2]:
        src = evt.get("source") or "External"
        evt_id = evt.get("event_id") or "unknown"
        purl = evt.get("provenance_url")
        if purl:
            verification_lines.append(f"[{src} Event {evt_id}]({purl})")

    if verification_lines:
        best_output += "\n\n---\n**Verify:** " + " · ".join(verification_lines)

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
