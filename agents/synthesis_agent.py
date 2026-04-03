"""
agents/synthesis_agent.py
Agent 6 — Action & Execution Layer
Generates candidate responses via Granite LLM (watsonx.ai).
Beam search: generates BEAM_WIDTH candidates.
The Overseer selects by citation alignment — not token probability.
Key decision: which output state does validation authorize?
"""

import requests
import json
from config import (
    WATSONX_API_KEY, WATSONX_PROJECT_ID, WATSONX_URL,
    GRANITE_MODEL, BEAM_WIDTH, MAX_NEW_TOKENS
)


class SynthesisAgent:

    def __init__(self):
        self._token = None

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
            return raw_text.replace("```markdown", "").replace("```", "").strip()
        except Exception as e:
            print(f"[SYNTHESIS] Granite call failed (beam {beam_idx}): {e}")
            return ""

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
        
        # Extract the source-of-truth agency provided by the Orchestrator
        target_agency = intent.get('regulatory_agency', 'relevant state authorities')

        return f"""You are the automated intelligence routing core for a 911 Computer-Aided Dispatch (CAD) system.
Your end-user is a highly trained Emergency Dispatcher. They are currently managing a live crisis.

IMPERATIVE RULES FOR RESPONSE GENERATION:
1. ZERO CONVERSATION: Do not use greetings, pleasantries, or conversational filler. 
2. ROLE BOUNDARIES: Your sole job is to provide inter-agency intelligence (USGS, CDC SVI, state policies).
3. STRICT FORMATTING: Use ONLY the exact markdown structure below. 
4. CITATION REQUIREMENT: You must cite: {citation} where policy is referenced.
5. Do NOT cite specific policy codes, regulation numbers, or document titles unless they appear verbatim in the retrieved context above. If no specific policy name is available, refer to 'applicable federal and state regulations' only.
6. REGULATORY ACCURACY: The primary state agency to notify is {target_agency}. Use this exact name and acronym in the [INTER-AGENCY ROUTING] section.

RETRIEVED POLICY/SVI CONTEXT:
{context[:1500]}

LIVE SEISMIC DATA (USGS):
{json.dumps(usgs)}

CIVILIAN CAD LOG (INCITING EVENT):
{intent.get('raw_input')}

GENERATE DISPATCH INTELLIGENCE BRIEF:
Use this exact format. Be clinical and concise.
OUTPUT ONLY THE RAW MARKDOWN. NO PREAMBLE. NO META-COMMENTARY. NO CODE BLOCKS.
**[HAZARD STATUS]** 1 sentence cross-referencing the CAD log with the LIVE SEISMIC DATA.
**[DEMOGRAPHIC RISK (SVI)]** 1 sentence detailing the vulnerability of the location based on retrieved context.
**[INTER-AGENCY ROUTING]** * Immediately notify the {target_agency} regarding site-specific operational status.
* Coordinate with the Federal Emergency Management Agency (FEMA) for support based on the SVI score and citation: {citation}.
"""

    def _get_iam_token(self) -> str:
        if self._token:
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
            self._token = r.json().get("access_token", "")
            return self._token
        except Exception as e:
            print(f"[SYNTHESIS] IAM token failed: {e}")
            return ""
