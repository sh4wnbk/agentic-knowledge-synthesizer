"""
agents/data_bridge_agent.py
Agent 4 — Tools Layer

Executes authorized API calls to federal, state, and NGO data stores.
USGS queries are location-aware — bounding box passed from Orchestrator
so results are geographically relevant to the citizen's crisis location.

Key decision: within legal data-sharing scope for this event?
"""

import requests
from config import USGS_API_URL, SEISMIC_MIN_MAGNITUDE


class DataBridgeAgent:

    def fetch(self, intent: dict, retrieval: dict, bbox: dict = None) -> dict:
        """
        Fetches live data after RAG retrieval.
        bbox: geographic bounding box from Orchestrator.get_bbox()
              constrains USGS query to the relevant region.
        """
        return {
            "usgs_live":      self._fetch_usgs_live(bbox),
            "fema_resources": self._fetch_fema(intent),
            "ngo_resources":  self._fetch_ngo(intent),
            "legal_scope_ok": self._verify_legal_scope(intent)
        }

    def _fetch_usgs_live(self, bbox: dict = None) -> dict:
        """
        Live USGS feed — M >= 3.0 events.
        Strictly bounded to regional bbox. Global fallback explicitly disabled
        to prevent CAD dashboard pollution.
        """
        if not bbox:
            return {
                "status": "ABORTED: No geographic bounding box provided. Location unresolved.",
                "source": "USGS Earthquake Hazards API"
            }

        params = {
            "format":       "geojson",
            "minmagnitude": SEISMIC_MIN_MAGNITUDE,
            "limit":        5,
            "orderby":      "time"
        }
        params.update(bbox)

        try:
            r = requests.get(USGS_API_URL, params=params, timeout=10)
            features = r.json().get("features", [])
            
            if not features:
                # Explicitly declare a negative result so the LLM doesn't hallucinate
                return {
                    "status": "CLEAR: NO RECENT SEISMIC EVENTS DETECTED IN REGION",
                    "region_scope": "regional",
                    "source": "USGS Earthquake Hazards API (real-time)"
                }

            latest = features[0]["properties"]
            coords = features[0].get("geometry", {}).get("coordinates", [])
            return {
                "status":       "HAZARD DETECTED: SEISMIC EVENT CONFIRMED",
                "latest_event": latest.get("place"),
                "magnitude":    latest.get("mag"),
                "depth_km":     coords[2] if len(coords) > 2 else "unknown",
                "region_scope": "regional",
                "event_count":  len(features),
                "source":       "USGS Earthquake Hazards API (real-time)"
            }
        except Exception as e:
            print(f"[BRIDGE] USGS live fetch failed: {e}")
            return {"status": "ERROR: USGS API Timeout", "source": "USGS (unavailable)"}

    def _fetch_fema(self, intent: dict) -> dict:
        # Production: authenticated FEMA API with Login.gov token.
        # Assumption: Login.gov digital identity pre-established.
        # Open question: state law governing PII sharing across agencies.
        return {
            "shelter_available":   True,
            "assistance_eligible": True,
            "source":              "FEMA NIMS (prototype stub)"
        }

    def _fetch_ngo(self, intent: dict) -> dict:
        # Production: Red Cross API, Municipal Housing registry.
        return {
            "red_cross_active": True,
            "hotline":          "1-800-RED-CROSS",
            "source":           "NGO database (prototype stub)"
        }

    def _verify_legal_scope(self, intent: dict) -> bool:
        """
        Verifies data sharing within legal scope for this event type.
        Open design question: state laws governing PII sharing across
        12+ agencies in earthquake-affected zones. (Blackman, 2025 — Week 2 unknowns)
        Prototype assumption: scope verified via Login.gov identity.
        """
        return True
