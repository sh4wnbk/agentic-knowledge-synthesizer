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
import re

from agents.synthesis_agent     import SynthesisAgent, SynthesisUnavailable
from governance.output_states   import AgentOutput, OutputState
from config                     import MAX_RETRIES


# ── Deterministic fact composition ────────────────────────────────────────────
# Established facts are composed here and injected verbatim, the same rule the
# routing table already follows. If a value was computed upstream, the model does
# not get to restate it: it dropped qualifiers (attaching a county-level emPOWER
# count to a census tract) and merged unrelated places. Each fact also carries
# the source that produced it, so a citation is never stapled onto a fact it did
# not support.

def _county_label(name) -> str:
    """
    Normalize a county name to exactly one trailing "County".

    The sources disagree: the CDC SVI COUNTY column already carries the word
    ("Mahoning County") while the emPOWER NAME column does not ("Mahoning").
    Appending unconditionally produced "Mahoning County County".
    """
    n = (name or "").strip()
    if not n:
        return ""
    return n if n.lower().endswith("county") else f"{n} County"


def _incident_place_label(bridge_data: dict, intent: dict) -> str:
    """Human label for the reported incident location, with county when known."""
    svi = bridge_data.get("svi_lookup") or {}
    label = (svi.get("resolved_location") or svi.get("location_text")
             or intent.get("location") or "the reported incident location")
    county = svi.get("county_name")
    state = svi.get("state_abbr") or svi.get("state_name")
    if county:
        suffix = _county_label(county)
        # Avoid "Youngstown, OH (Mahoning County, OH)" when the label already
        # carries the state.
        if state and state.upper() not in label.upper():
            suffix += f", {state}"
        return f"{label} ({suffix})"
    return label


def compose_hazard_facts(bridge_data: dict, intent: dict) -> str:
    """
    USGS event, its geographic relationship to the reported incident, and the EPA
    TRI facility list. When the nearest catalogued event is not the reported
    incident, that is stated explicitly rather than left for the reader to infer.
    """
    usgs = bridge_data.get("usgs_live") or {}
    epa  = bridge_data.get("epa_tri") or {}
    incident_place = _incident_place_label(bridge_data, intent)

    parts = []
    place = usgs.get("latest_event")
    mag   = usgs.get("magnitude")
    depth = usgs.get("depth_km")
    dist  = usgs.get("distance_from_incident_km")

    if place and mag is not None:
        depth_txt = f", depth {depth:.1f} km" if isinstance(depth, (int, float)) else ""
        parts.append(f"Nearest catalogued seismic event: M{mag} {place}{depth_txt} (USGS).")
        if isinstance(dist, (int, float)):
            if dist < 30:
                parts.append(
                    f"That event is {round(dist, 1)} km from the reported incident at "
                    f"{incident_place} and is treated as co-located (USGS)."
                )
            else:
                parts.append(
                    f"This is NOT the reported incident location: the catalogued event is "
                    f"{round(dist, 1)} km away, and the demographic data below describes "
                    f"{incident_place}, not the event location (USGS)."
                )
    else:
        parts.append("No seismic events detected in the regional scope (USGS).")

    if epa.get("hazmat_detected"):
        count = epa.get("facility_count")
        names = ", ".join(f.get("name", "Unknown") for f in (epa.get("facilities") or [])[:5])
        plural = "ies" if count != 1 else "y"
        parts.append(
            f"COMPOUND HAZMAT RISK: {count} TRI-listed facilit{plural} within the incident "
            f"bounding box: {names} (EPA TRI)."
        )
    else:
        parts.append("No TRI-listed hazmat facilities detected in the incident bounding box (EPA TRI).")

    return " ".join(parts)


def compose_demographic_facts(bridge_data: dict) -> str:
    """
    Tract-level SVI and county-level emPOWER, each labelled with the geographic
    level it is actually reported at. emPOWER is a county figure and saying so is
    not optional: attached to a tract it implies a wildly wrong share of residents.
    """
    svi_d = bridge_data.get("svi_data") or {}
    svi_l = bridge_data.get("svi_lookup") or {}
    emp   = bridge_data.get("empower_data") or {}

    tract  = svi_d.get("tract_geoid") or svi_l.get("tract_geoid")
    county = svi_d.get("county_name") or svi_l.get("county_name")
    state  = svi_d.get("state_abbr") or svi_l.get("state_abbr")
    score  = svi_d.get("svi_score", svi_l.get("overall_svi"))
    approx = svi_d.get("approximate", svi_l.get("approximate", False))

    parts = []
    if tract:
        where = f"Census Tract {tract}"
        if county:
            where += f", {_county_label(county)}"
        if state:
            where += f", {state}"
        parts.append(f"Location resolved to {where}{' (approximate match)' if approx else ''}.")

    if isinstance(score, (int, float)):
        band = " (HIGH vulnerability, top quartile)" if score > 0.75 else ""
        parts.append(f"Tract-level SVI percentile {score:.4f}{band} (CDC/ATSDR SVI 2022).")
    else:
        parts.append("Tract-level SVI percentile unavailable (CDC/ATSDR SVI 2022).")

    count = emp.get("electricity_dependent_count")
    if emp.get("status") == "unavailable" or count is None:
        parts.append("County-level electricity-dependent beneficiary count unavailable (HHS emPOWER).")
    else:
        emp_county = _county_label(emp.get("county_name") or county) or "the reporting county"
        parts.append(
            f"COUNTY-LEVEL figure, not tract-level: {count} electricity-dependent Medicare "
            f"beneficiaries across all of {emp_county} (HHS emPOWER, reported by county)."
        )

    return " ".join(parts)


def run_pipeline(
    raw_input: str,
    *,
    intake: IntakeAgent           = None,
    orchestrator: OrchestratorAgent = None,
    rag: RAGKnowledgeAgent        = None,
    bridge: DataBridgeAgent       = None,
    overseer: OverseerAgent       = None,
    synthesis: SynthesisAgent     = None,
) -> AgentOutput:
    # Use provided instances (avoids double model-load in server context)
    # or create new ones when called standalone (tests, CLI).
    if intake is None:
        intake = IntakeAgent()
    if orchestrator is None:
        orchestrator = OrchestratorAgent()
    if rag is None:
        rag = RAGKnowledgeAgent()
    if bridge is None:
        bridge = DataBridgeAgent()
    if overseer is None:
        overseer = OverseerAgent()
    if synthesis is None:
        synthesis = SynthesisAgent()

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
        # Every beam came back empty. This is a provider/infrastructure failure,
        # not an evidence-based refusal, so it must surface loudly rather than as
        # an HONEST_FALLBACK the dispatcher would read as a governed decision.
        raise SynthesisUnavailable(
            "All beams returned empty text. The LLM provider produced no usable "
            "output (check credentials, endpoint, or MAX_NEW_TOKENS for reasoning "
            "models). This is an infrastructure failure, not an honest fallback."
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
        if not candidates:
            raise SynthesisUnavailable(
                "All beams returned empty text on retry. Provider/infrastructure "
                "failure, not an honest fallback."
            )
        citation    = retrieval.get("citation")
        context     = retrieval.get("context", "")
        best_output = None
        best_score  = -1.0

    # ── Replace [HAZARD STATUS] and [DEMOGRAPHIC RISK (SVI)] with facts ──
    # Same rule the routing table already follows. The model conflated the USGS
    # place name with the reported incident, and attached a county-level emPOWER
    # count to a census tract, so it no longer gets to restate either. Composed in
    # Python and inserted verbatim, after Overseer scoring so citation alignment
    # is still measured against what the model actually wrote.
    hazard_facts      = compose_hazard_facts(bridge_data, intent)
    demographic_facts = compose_demographic_facts(bridge_data)

    best_output = re.sub(
        r"\*?\*?\[HAZARD STATUS\]\*?\*?.*?(?=\*?\*?\[DEMOGRAPHIC)",
        lambda m: f"**[HAZARD STATUS]** {hazard_facts}\n\n",
        best_output,
        count=1,
        flags=re.DOTALL,
    )

    def _demographic_repl(m):
        # Keep the model's qualitative clause only when it states no figures of
        # its own: anything numeric it wrote here was a restatement of a value
        # composed above, which is exactly how the county/tract mixup happened.
        prose = (m.group(1) or "").strip()
        if not prose or re.search(r"\d", prose):
            prose = ""
        body = f"{demographic_facts} {prose}".strip()
        return f"**[DEMOGRAPHIC RISK (SVI)]** {body}\n\n"

    best_output = re.sub(
        r"\*?\*?\[DEMOGRAPHIC RISK \(SVI\)\]\*?\*?(.*?)(?=\*?\*?\[INTER-AGENCY)",
        _demographic_repl,
        best_output,
        count=1,
        flags=re.DOTALL,
    )

    # ── Replace [INTER-AGENCY ROUTING] with deterministic table ──
    # The LLM reliably truncates table rows. Generate from bridge data
    # directly so every agency appears and tier promotion is reflected.
    # Injected after Overseer scoring so it does not affect citation alignment.
    agency_brief = bridge_data.get("agency_routing", {})
    if agency_brief and any(
        agency_brief.get(k) for k in ("tier_1_immediate", "tier_2_within_hour", "tier_3_as_warranted")
    ):
        # Contact renders as a real Markdown link so the dashboard's Markdown pass
        # turns it into a clickable tel:/mailto: anchor rather than literal text.
        # (The old code appended the bare hotline to the role cell, so it showed as
        # unclickable plain text.) Numbers are the bare, verified values from
        # AGENCY_ROUTING; an agency with none gets a dash placeholder, never a guess.
        def _contact_cell(agency):
            bits = []
            tel = agency.get("phone") or agency.get("hotline")
            if tel:
                bits.append(f"[{tel}](tel:{tel})")
            if agency.get("email"):
                bits.append(f"[{agency['email']}](mailto:{agency['email']})")
            return " · ".join(bits) if bits else "—"

        table_rows = ["| Tier | Agency | Role | Contact |", "|---|---|---|---|"]
        for agency in agency_brief.get("tier_1_immediate", []):
            table_rows.append(f"| 1 — IMMEDIATE | {agency['name']} | {agency.get('role','')} | {_contact_cell(agency)} |")
        for agency in agency_brief.get("tier_2_within_hour", []):
            table_rows.append(f"| 2 — WITHIN HOUR | {agency['name']} | {agency.get('role','')} | {_contact_cell(agency)} |")
        for agency in agency_brief.get("tier_3_as_warranted", []):
            table_rows.append(f"| 3 — AS WARRANTED | {agency['name']} | {agency.get('role','')} | {_contact_cell(agency)} |")
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
