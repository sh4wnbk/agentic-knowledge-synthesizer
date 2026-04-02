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
            return result.get("results", [{}])[0].get("generated_text", "")
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
        RAG-grounded prompt.
        Retrieved context is injected before the instruction.
        The LLM reasons over what was retrieved — not over
        its own parametric knowledge.
        """
        context  = retrieval.get("context", "No context retrieved.")
        citation = retrieval.get("citation", "No citation available.")
        fema     = bridge.get("fema_resources", {})
        ngo      = bridge.get("ngo_resources", {})
        usgs     = bridge.get("usgs_live", {})

        return f"""You are an emergency aid coordination assistant operating during an active crisis.

RETRIEVED KNOWLEDGE BASE CONTEXT (cite this — do not fabricate beyond it):
{context[:1500]}

LIVE SEISMIC DATA:
{json.dumps(usgs)}

AVAILABLE RESOURCES:
- Federal (FEMA): {json.dumps(fema)}
- NGO: {json.dumps(ngo)}

CITIZEN CRISIS INPUT:
{intent.get('raw_input')}

INSTRUCTION:
Provide a clear, specific aid coordination response.
You must cite: {citation}
Do not include information not present in the retrieved context above.
Do not fabricate resource availability, locations, or assistance amounts.
Be direct. The citizen is in crisis.

RESPONSE:"""

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
