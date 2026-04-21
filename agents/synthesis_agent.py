"""
agents/synthesis_agent.py
Agent 6 — Action & Execution Layer
Generates candidate responses via Granite LLM (watsonx.ai).
Beam search: generates BEAM_WIDTH candidates.
The Overseer selects by citation alignment — not token probability.
Key decision: which output state does validation authorize?
"""

import time
import requests
import json
import re
from config import (
    WATSONX_API_KEY, WATSONX_PROJECT_ID, WATSONX_URL,
    GRANITE_MODEL, BEAM_WIDTH, MAX_NEW_TOKENS
)


class SynthesisAgent:

    def __init__(self):
        self._token = None
        self._token_expiry = 0  # Unix timestamp

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
        token   = self._get_iam_token()
        prompt  = self._build_prompt(intent, retrieval, bridge)
        candidates = []

        for beam in range(BEAM_WIDTH):
            response = self._call_granite(token, prompt, beam)
            if response:
                candidates.append(response)

        print(f"[SYNTHESIS] Generated {len(candidates)} candidates "
              f"for Overseer evaluation.")
        return candidates

    def _call_granite(self, token: str, prompt: str, beam_idx: int) -> str:
        """
        Single Granite LLM call.
        Temperature varies slightly per beam to produce
        meaningfully different candidates.
        beam_idx=0 is near-greedy; subsequent beams allow more sampling.
        """
        temperature = 0.3 + (beam_idx * 0.15)  # 0.3, 0.45, 0.60, 0.75

        payload = {
            "model_id":   GRANITE_MODEL,
            "project_id": WATSONX_PROJECT_ID,
            "input":      prompt,
            "parameters": {
                "decoding_method": "sample",   # Sampling, not greedy
                "temperature":     temperature,
                "max_new_tokens":  MAX_NEW_TOKENS,
                "repetition_penalty": 1.1
            }
        }

        try:
            r = requests.post(
                f"{WATSONX_URL}/ml/v1/text/generation?version=2023-05-29",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json"
                },
                json=payload,
                timeout=30
            )
            result = r.json()
            raw_text = result.get("results", [{}])[0].get("generated_text", "")
            raw_text = raw_text.replace("```markdown", "").replace("```", "").strip()
            # Strip any preamble Granite generates before the first section header.
            # The output contract requires [HAZARD STATUS] to be the opening line.
            for marker in ["**[HAZARD STATUS]**", "[HAZARD STATUS]"]:
                idx = raw_text.find(marker)
                if idx > 0:
                    raw_text = raw_text[idx:]
                    break
            raw_text = self._normalize_section_headers(raw_text)
            return raw_text
        except Exception as e:
            print(f"[SYNTHESIS] Granite call failed (beam {beam_idx}): {e}")
            return ""

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
            empower_display = f"County: {edep_count} electricity-dependent Medicare beneficiaries"

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
7. If the SVI lookup is available, explicitly name the census tract GEOID and overall SVI percentile in the [DEMOGRAPHIC RISK (SVI)] section. If the lookup is approximate, say so.
8. If SVI > 0.75, describe it as HIGH or significant vulnerability. Never describe it as moderate.
9. Express SVI as a decimal (for example 0.9575), not a percentage.

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
**[HAZARD STATUS]** 1 sentence stating the confirmed USGS magnitude, depth, and location, followed by the geographic_note value exactly as it appears in the LIVE SEISMIC DATA above (do not paraphrase or add prefixes). If no seismic event is detected, state "No seismic events detected in the regional scope." Include: {hazmat_note}.
**[DEMOGRAPHIC RISK (SVI)]** 1 sentence detailing the vulnerability of the location based on retrieved context. If applicable, include: {svi_display}. {empower_display}. Tract: {svi_tract}.
**[INTER-AGENCY ROUTING]** List the primary regulatory agency and its immediate action. Do not list all agencies — the full routing table is appended automatically.
"""

    def _get_iam_token(self) -> str:
        # Refresh if missing or expiring within 60 seconds
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        try:
            r = requests.post(
                "https://iam.cloud.ibm.com/identity/token",
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey":     WATSONX_API_KEY
                },
                timeout=15
            )
            payload = r.json()
            self._token = payload.get("access_token", "")
            self._token_expiry = time.time() + payload.get("expires_in", 3600)
            return self._token
        except Exception as e:
            print(f"[SYNTHESIS] IAM token failed: {e}")
            return ""
