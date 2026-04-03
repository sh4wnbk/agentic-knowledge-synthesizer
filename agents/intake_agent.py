"""
agents/intake_agent.py
Upgraded to ensure regional state extraction and plural keyword support.
"""

from typing import Optional

class IntakeAgent:
    # (transcribe method remains unchanged)

    def parse(self, raw_input: str) -> dict:
        """
        Structures intent to bridge the Perception-to-Reasoning gap.
        """
        text_lower = raw_input.lower()
        
        # 1. CRISIS EXTRACTION (Expanded for plural and damage signals)
        crisis_type = None
        seismic_keys = ["earthquake", "shaking", "tremor", "tremors", "seismic", "quake", "cracking"]
        if any(w in text_lower for w in seismic_keys):
            crisis_type = "induced_seismicity"
        elif "flood" in text_lower:
            crisis_type = "flooding"

        # 2. STATE EXTRACTION (Critical for Orchestrator routing clusters)
        state = None
        if "ohio" in text_lower or " oh " in f" {text_lower} " or "youngstown" in text_lower:
            state = "Ohio"
        elif "oklahoma" in text_lower or " ok " in f" {text_lower} " or "tulsa" in text_lower:
            state = "Oklahoma"

        # 3. LOCATION EXTRACTION
        location = raw_input if any(w in text_lower for w in ["street", "ave", "near"]) else None

        return {
            "raw_input":   raw_input,
            "location":    location,
            "state":       state,        # This enables the 'reasoning_oklahoma' cluster
            "crisis_type": crisis_type,
            "is_complete": bool(location and crisis_type)
        }