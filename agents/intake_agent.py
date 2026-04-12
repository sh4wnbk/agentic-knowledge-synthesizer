"""
agents/intake_agent.py
Perception layer — extracts crisis type, state, and location from raw input.
"""

from typing import Optional


# Known Ohio cities and counties → normalized location string
OHIO_LOCATIONS = {
    "youngstown": "Youngstown, OH",
    "mahoning":   "Youngstown, OH",
    "warren":     "Warren, OH",
    "trumbull":   "Warren, OH",
    "canton":     "Canton, OH",
    "stark":      "Canton, OH",
    "akron":      "Akron, OH",
    "summit":     "Akron, OH",
    "cleveland":  "Cleveland, OH",
    "cuyahoga":   "Cleveland, OH",
    "columbus":   "Columbus, OH",
    "franklin":   "Columbus, OH",
    "toledo":     "Toledo, OH",
    "dayton":     "Dayton, OH",
    "cincinnati": "Cincinnati, OH",
}

# Known Oklahoma cities and counties → normalized location string
OKLAHOMA_LOCATIONS = {
    "tulsa":          "Tulsa, OK",
    "cushing":        "Cushing, OK",
    "payne":          "Stillwater, OK",
    "stillwater":     "Stillwater, OK",
    "oklahoma city":  "Oklahoma City, OK",
    "oklahoma":       "Oklahoma City, OK",
    "norman":         "Norman, OK",
    "cleveland":      "Norman, OK",
    "enid":           "Enid, OK",
    "garfield":       "Enid, OK",
    "ardmore":        "Ardmore, OK",
    "lawton":         "Lawton, OK",
    "edmond":         "Edmond, OK",
    "ponca city":     "Ponca City, OK",
}

ADDRESS_KEYWORDS = [
    "street", "st ", " st,", "avenue", "ave", "road", "rd",
    "highway", "hwy", "boulevard", "blvd", "drive", "dr",
    "lane", "ln", "court", "ct", "way", "place", "pl",
]


class IntakeAgent:

    def parse(self, raw_input: str) -> dict:
        """
        Structures intent to bridge the Perception-to-Reasoning gap.
        """
        text_lower = raw_input.lower()

        # 1. CRISIS EXTRACTION
        crisis_type = None
        seismic_keys = [
            "earthquake", "shaking", "tremor", "tremors",
            "seismic", "quake", "cracking", "magnitude", " m2", " m3", " m4"
        ]
        if any(w in text_lower for w in seismic_keys):
            crisis_type = "induced_seismicity"
        elif "flood" in text_lower:
            crisis_type = "flooding"

        # 2. STATE EXTRACTION
        state = None
        if "ohio" in text_lower or " oh " in f" {text_lower} " or " oh," in text_lower:
            state = "Ohio"
        elif "oklahoma" in text_lower or " ok " in f" {text_lower} " or " ok," in text_lower:
            state = "Oklahoma"

        # Infer state from city/county if not yet detected
        if not state:
            for key in OHIO_LOCATIONS:
                if key in text_lower:
                    state = "Ohio"
                    break
        if not state:
            for key in OKLAHOMA_LOCATIONS:
                if key in text_lower:
                    state = "Oklahoma"
                    break

        # 3. LOCATION EXTRACTION — city/county lookup first
        location = None

        if state == "Ohio":
            for key, val in OHIO_LOCATIONS.items():
                if key in text_lower:
                    location = val
                    break
        elif state == "Oklahoma":
            for key, val in OKLAHOMA_LOCATIONS.items():
                if key in text_lower:
                    location = val
                    break

        # Street address fallback
        if not location and any(w in text_lower for w in ADDRESS_KEYWORDS):
            location = raw_input

        # Coordinate fallback
        if not location:
            import re
            coord = re.search(r'-?\d{1,2}\.\d+\s*,\s*-?\d{1,3}\.\d+', raw_input)
            if coord:
                location = raw_input

        # State-level fallback — pipeline can still route and fetch USGS data
        # even without a specific city; SVI lookup will degrade gracefully.
        if not location and state:
            location = state

        return {
            "raw_input":   raw_input,
            "location":    location,
            "state":       state,
            "crisis_type": crisis_type,
            "is_complete": bool(location and crisis_type)
        }