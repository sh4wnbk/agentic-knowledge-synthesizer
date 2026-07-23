"""
agents/synthesis_agent.py
Agent 6, the Action and Execution Layer.

Generates candidate responses through a pluggable LLM provider (see
providers/). Beam search produces BEAM_WIDTH candidates and the Overseer
selects by citation alignment, not by token probability.

Key decision: which output state does validation authorize?

The model vendor is an implementation detail. Everything that makes this
AEGIS (the prompt contract, the three required section headers, the beam
schedule, the refusal to deliver an unvalidated brief) lives here and is
provider-agnostic.
"""

import json
import re
from config import (
    BEAM_WIDTH, MAX_NEW_TOKENS,
    BEAM_BASE_TEMPERATURE, BEAM_TEMPERATURE_STEP,
)


class SynthesisUnavailable(RuntimeError):
    """
    Every beam returned empty text: an infrastructure/provider failure, not an
    evidence-based refusal. It must surface distinctly rather than collapse into
    HONEST_FALLBACK, so a broken or misconfigured provider is loud instead of
    masquerading as a governed "I could not support this claim."
    """
    pass


class SynthesisAgent:

    def __init__(self, provider=None):
        """
        provider: an LLMProvider instance. Injected for testing, or left
        None to resolve from LLM_PROVIDER / auto-detected credentials on
        first use. Resolution is lazy so importing this module never
        requires credentials.
        """
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            from providers import get_provider
            self._provider = get_provider()
        return self._provider

    def generate_candidates(
        self,
        intent: dict,
        retrieval: dict,
        bridge: dict
    ) -> list:
        """
        Generates BEAM_WIDTH candidate responses.
        Each candidate is independently scored by the Overseer
        for citation alignment before one is selected for delivery.

        This replaces greedy decoding (top-1 most probable token)
        with a selection process grounded in logical consistency
        with the retrieved source — not token probability.
        """
        prompt = self._build_prompt(intent, retrieval, bridge)
        candidates = []

        for beam in range(BEAM_WIDTH):
            response = self._generate_candidate(prompt, beam)
            if response:
                candidates.append(response)

        print(f"[SYNTHESIS] Generated {len(candidates)} candidates "
              f"via {self.provider.name} for Overseer evaluation.")
        return candidates

    def _generate_candidate(self, prompt: str, beam_idx: int) -> str:
        """
        One beam. Temperature varies per beam so the candidates differ
        meaningfully: beam 0 is near-greedy, later beams sample more freely.
        A provider failure returns an empty string and the beam is dropped.
        """
        temperature = round(
            BEAM_BASE_TEMPERATURE + (beam_idx * BEAM_TEMPERATURE_STEP), 4
        )
        raw_text = self.provider.generate(
            prompt=prompt,
            temperature=temperature,
            max_tokens=MAX_NEW_TOKENS,
        )
        if not raw_text:
            return ""
        return self._clean_candidate(raw_text)

    @classmethod
    def _clean_candidate(cls, raw_text: str) -> str:
        """
        Enforce the output contract on whatever the provider returned.
        Provider-agnostic: every model tested wraps or prefaces its markdown
        in some way, and the Overseer's structural check is unforgiving.
        """
        raw_text = raw_text.replace("```markdown", "").replace("```", "").strip()
        # Strip any preamble before the first section header. The output
        # contract requires [HAZARD STATUS] to be the opening line.
        for marker in ["**[HAZARD STATUS]**", "[HAZARD STATUS]"]:
            idx = raw_text.find(marker)
            # Accept idx == 0 too: when the balanced "**[HAZARD STATUS]**" marker
            # is already at the start, keep it. The old "> 0" skipped it and fell
            # through to the bare "[HAZARD STATUS]" marker at idx 2, which sliced
            # off the leading "**" and produced an unbalanced header.
            if idx >= 0:
                raw_text = raw_text[idx:]
                break
        return cls._normalize_section_headers(raw_text)

    @staticmethod
    def _normalize_section_headers(text: str) -> str:
        """Force the three dispatch section headers into a consistent markdown form."""
        replacements = {
            r"^\*\*?\[HAZARD STATUS\]\*\*?": "**[HAZARD STATUS]**",
            r"^\*\*?\[DEMOGRAPHIC RISK \(SVI\)\]\*\*?": "**[DEMOGRAPHIC RISK (SVI)]**",
            r"^\*\*?\[INTER-AGENCY ROUTING\]\*\*?": "**[INTER-AGENCY ROUTING]**",
        }
        lines = text.splitlines()
        normalized = []
        for line in lines:
            stripped = line.lstrip()
            replaced = False
            for pattern, header in replacements.items():
                if re.match(pattern, stripped):
                    normalized.append(re.sub(pattern, header, stripped))
                    replaced = True
                    break
            if not replaced:
                normalized.append(line)
        return "\n".join(normalized)

    def _build_prompt(
        self,
        intent: dict,
        retrieval: dict,
        bridge: dict
    ) -> str:
        """
        RAG-grounded prompt with explicit regulatory agency injection.
        This prevents 'acronym drift' by providing the specific agency 
        name and acronym resolved by the Orchestrator.
        """
        context  = retrieval.get("context", "No context retrieved.")
        citation = retrieval.get("citation", "No citation available.")
        usgs     = bridge.get("usgs_live", {})
        svi      = bridge.get("svi_data") or bridge.get("svi_lookup", {})
        agency_data = bridge.get("agency_routing", {})
        external_ops = bridge.get("external_operational_picture", {})
        empower_data = bridge.get("empower_data", {})
        epa_tri      = bridge.get("epa_tri", {})
        
        # Extract the source-of-truth agency provided by the Orchestrator
        target_agency = intent.get('regulatory_agency', 'relevant state authorities')

        svi_score = svi.get("svi_score")
        svi_tract = svi.get("tract_name") or svi.get("tract_geoid", "")
        if isinstance(svi_score, (int, float)):
            if svi_score > 0.75:
                svi_display = f"SVI percentile: {svi_score:.4f} (HIGH vulnerability — top quartile)"
            else:
                svi_display = f"SVI percentile: {svi_score:.4f}"
        else:
            svi_display = "SVI data unavailable"

        # HHS emPOWER — electricity-dependent residents
        edep_count = empower_data.get("electricity_dependent_count")
        if empower_data.get("status") == "unavailable" or edep_count is None:
            empower_display = "emPOWER data unavailable"
        else:
            # emPOWER is reported by county FIPS, never by tract. Carry that
            # qualifier on the value itself so it cannot be silently dropped.
            empower_display = (
                f"{edep_count} electricity-dependent Medicare beneficiaries "
                f"COUNTY-WIDE (county-level figure, not tract-level)"
            )

        # EPA TRI — hazmat facilities
        if epa_tri.get("hazmat_detected"):
            facility_names = ", ".join(
                f.get("name", "Unknown") for f in epa_tri.get("facilities", [])[:5]
            )
            hazmat_note = (
                f"COMPOUND RISK: {epa_tri['facility_count']} TRI-listed "
                f"facilit{'ies' if epa_tri['facility_count'] != 1 else 'y'} "
                f"within incident bbox: {facility_names}"
            )
        else:
            hazmat_note = "No TRI-listed hazmat facilities detected in incident bbox"

        def fmt_tier(agencies):
            if not agencies:
                return "  None identified"
            return "\n".join(
                f"  - {agency['name']}: {agency['role']}" +
                (f" | Hotline: {agency['hotline']}" if agency.get("hotline") else "")
                for agency in agencies
            )

        if agency_data:
            agency_block = (
                f"TIER 1 — IMMEDIATE NOTIFICATION:\n{fmt_tier(agency_data.get('tier_1_immediate', []))}\n\n"
                f"TIER 2 — WITHIN THE HOUR:\n{fmt_tier(agency_data.get('tier_2_within_hour', []))}\n\n"
                f"TIER 3 — AS WARRANTED:\n{fmt_tier(agency_data.get('tier_3_as_warranted', []))}"
            )
        else:
            agency_block = f"Primary agency: {target_agency}"

        return f"""You are the automated intelligence routing core for a 911 Computer-Aided Dispatch (CAD) system.
Your end-user is a highly trained Emergency Dispatcher. They are currently managing a live crisis.

IMPERATIVE RULES FOR RESPONSE GENERATION:
1. ZERO CONVERSATION: Do not use greetings, pleasantries, or conversational filler. 
2. ROLE BOUNDARIES: Your sole job is to provide inter-agency intelligence (USGS, CDC SVI, state policies).
3. STRICT FORMATTING: Use ONLY the exact markdown structure below. 
4. CITATION REQUIREMENT: You must cite: {citation} where policy is referenced.
5. Do NOT cite specific policy codes, regulation numbers, or document titles unless they appear verbatim in the retrieved context above. If no specific policy name is available, refer to 'applicable federal and state regulations' only.
6. REGULATORY ACCURACY: The primary state agency to notify is {target_agency}. Use this exact name and acronym in the [INTER-AGENCY ROUTING] section.
7. DETERMINISTIC VALUES: Do NOT state census tract IDs, county names, place names, SVI percentiles, magnitudes, depths, distances, facility counts, or beneficiary counts. Every one of those is composed in code and injected verbatim after generation. Restating them is how a county-level count gets attached to a single census tract.
8. Describe vulnerability qualitatively (for example HIGH or significant) in words only, never with a number.

RETRIEVED POLICY/SVI CONTEXT:
{context[:1500]}

DETERMINISTIC SVI LOOKUP:
{json.dumps(svi, indent=2)}

HHS EMPOWER (ELECTRICITY-DEPENDENT RESIDENTS):
{json.dumps(empower_data, indent=2)}

LIVE SEISMIC DATA (USGS):
{json.dumps(usgs)}

EPA TRI FACILITIES (HAZMAT RISK):
{json.dumps(epa_tri, indent=2)}

HARMONIZED EXTERNAL OPERATIONS (FEMA + IFRC):
{json.dumps(external_ops, indent=2)}

AUTHORIZED AGENCY ROUTING:
{agency_block}

CIVILIAN CAD LOG (INCITING EVENT):
{intent.get('raw_input')}

GENERATE DISPATCH INTELLIGENCE BRIEF:
Use this exact format. Be clinical and concise.
OUTPUT ONLY THE RAW MARKDOWN. NO PREAMBLE. NO META-COMMENTARY. NO CODE BLOCKS.
DO NOT add any other headings, clarifications, or parenthetical notes.
DO NOT add any section before [HAZARD STATUS]. The first line of output must be **[HAZARD STATUS]** with no preceding text, bullets, or whitespace.
Use only these three section headers and nothing else:
**[HAZARD STATUS]** 1 short sentence framing what the seismic and hazmat picture means for the dispatcher. The event facts (magnitude, depth, place name, distance to the reported incident) and the TRI facility list are composed in code and replace this line after generation, so state no figures and no place names here.
**[DEMOGRAPHIC RISK (SVI)]** 1 short qualitative sentence, grounded in the retrieved context, on what the vulnerability means for response. State NO numbers, tract IDs, county names, percentiles, or counts: those are composed in code and injected. Context values for your understanding only, do not restate: {svi_display}; {empower_display}; tract {svi_tract}.
**[INTER-AGENCY ROUTING]** List the primary regulatory agency and its immediate action. Do not list all agencies — the full routing table is appended automatically.
"""
