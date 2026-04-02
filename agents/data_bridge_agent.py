"""
agents/data_bridge_agent.py
Agent 4 — Tools Layer
Executes authorized API calls to federal, state, and NGO data stores.
Key decision: within legal data-sharing scope for this event?
"""

import requests
from config import USGS_API_URL, CDC_SVI_URL


class DataBridgeAgent:

    def fetch(self, intent: dict, retrieval: dict) -> dict:
        """
        Fetches supplementary live data after RAG retrieval.
        Note: retrieval constrains what is fetched —
        RAG context determines which APIs are relevant.
        """
        return {
            "usgs_live":       self._fetch_usgs_live(),
            "fema_resources":  self._fetch_fema(intent),
            "ngo_resources":   self._fetch_ngo(intent),
            "legal_scope_ok":  self._verify_legal_scope(intent)
        }

    def _fetch_usgs_live(self) -> dict:
        """
        Live USGS feed — most recent M >= 3.0 events.
        Supplements the RAG-retrieved historical context
        with real-time seismic telemetry.
        """
        try:
            params = {
                "format":       "geojson",
                "minmagnitude": 3.0,
                "limit":        3,
                "orderby":      "time"
            }
            r = requests.get(USGS_API_URL, params=params, timeout=10)
            features = r.json().get("features", [])
            if features:
                latest = features[0]["properties"]
                return {
                    "latest_event": latest.get("place"),
                    "magnitude":    latest.get("mag"),
                    "source":       "USGS real-time"
                }
        except Exception as e:
            print(f"[BRIDGE] USGS live fetch failed: {e}")
        return {}

    def _fetch_fema(self, intent: dict) -> dict:
        # Production: authenticated FEMA API call with Login.gov token.
        # Prototype: stubbed response representing confirmed eligibility.
        return {
            "shelter_available":   True,
            "assistance_eligible": True,
            "source":              "FEMA NIMS (stubbed)"
        }

    def _fetch_ngo(self, intent: dict) -> dict:
        # Production: Red Cross API, Municipal Housing registry.
        return {
            "red_cross_active": True,
            "hotline":          "1-800-RED-CROSS",
            "source":           "NGO database (stubbed)"
        }

    def _verify_legal_scope(self, intent: dict) -> bool:
        """
        Verifies that data sharing is within the legal scope
        established for this event type.
        Assumption: Login.gov digital identity pre-established.
        Open question: state law governing PII sharing across agencies.
        """
        # Prototype assumption: scope verified.
        return True
