"""
agents/intake_agent.py
Agent 1 — Perception Layer
Parses unstructured crisis input into a structured intent.
Watson Speech-to-Text handles audio ingestion.
Key decision: valid crisis trigger, or prompt the citizen?
"""

import requests
from typing import Optional
from config import WATSON_STT_KEY, WATSON_STT_URL


class IntakeAgent:

    def transcribe(self, audio_path: str) -> Optional[str]:
        """
        Watson Speech-to-Text API.
        Converts 911 audio transcript to text.
        """
        if not audio_path or not WATSON_STT_KEY:
            return None
        try:
            with open(audio_path, "rb") as audio:
                response = requests.post(
                    f"{WATSON_STT_URL}/v1/recognize",
                    auth=("apikey", WATSON_STT_KEY),
                    headers={"Content-Type": "audio/wav"},
                    data=audio.read(),
                    timeout=30
                )
            result = response.json()
            return result["results"][0]["alternatives"][0]["transcript"]
        except Exception as e:
            print(f"[INTAKE] STT failed: {e}")
            return None

    def parse(self, raw_input: str) -> dict:
        """
        Structures raw text into a typed intent schema.
        """
        location    = self._extract_location(raw_input)
        crisis_type = self._extract_crisis_type(raw_input)

        return {
            "raw_input":   raw_input,
            "location":    location,
            "crisis_type": crisis_type,
            "is_complete": bool(location and crisis_type)
        }

    def _extract_location(self, text: str) -> Optional[str]:
        """
        Naive keyword extraction — placeholder for
        watsonx.ai NER model in production.
        """
        location_signals = [
            "street", "avenue", "road", "drive", "boulevard",
            "county", "city", "near", "district", "neighborhood"
        ]
        if any(w in text.lower() for w in location_signals):
            return text
        # If no location signal found, return the full text
        # and let the Overseer's input audit decide.
        return text if len(text) > 10 else None

    def _extract_crisis_type(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        if any(w in text_lower for w in
               ["earthquake", "shaking", "tremor", "seismic", "quake"]):
            return "induced_seismicity"
        if any(w in text_lower for w in ["flood", "flooding", "water"]):
            return "flooding"
        if any(w in text_lower for w in ["fire", "burning", "smoke"]):
            return "fire"
        return None
