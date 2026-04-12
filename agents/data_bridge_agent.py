"""
agents/data_bridge_agent.py
Agent 4 — Tools Layer

Executes authorized API calls to federal, state, and NGO data stores.
USGS queries are location-aware — bounding box passed from Orchestrator
so results are geographically relevant to the citizen's crisis location.

Key decision: within legal data-sharing scope for this event?
"""

import csv
import re
from functools import lru_cache

import requests
from config import (
    CENSUS_GEOCODER_BENCHMARK,
    CENSUS_GEOCODER_URL,
    CENSUS_GEOCODER_VINTAGE,
    CDC_SVI_CSV,
    SEISMIC_MIN_MAGNITUDE,
    USGS_API_URL,
)


CITY_CENTER_FALLBACKS = {
    "youngstown, oh": {"lat": 41.0998, "lon": -80.6495, "source": "city_center_proxy"},
    "tulsa, ok": {"lat": 36.15398, "lon": -95.99277, "source": "city_center_proxy"},
}


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
            "svi_lookup":     self._lookup_svi(intent),
            "legal_scope_ok": self._verify_legal_scope(intent)
        }

    def _lookup_svi(self, intent: dict) -> dict:
        """
        Resolves a tract from the incident location and joins it to
        the local CDC SVI 2022 tract dataset.

        Exact street addresses or coordinates are preferred. If the
        input only names a city, a city-center proxy is used and the
        result is marked approximate.
        """
        location_text = (
            intent.get("location")
            or intent.get("raw_input")
            or ""
        ).strip()

        if not location_text:
            return {
                "status": "unavailable",
                "reason": "No location text provided",
                "source": "Census Geocoder + CDC SVI 2022"
            }

        coords_info = self._resolve_coordinates(location_text)
        if not coords_info:
            return {
                "status": "unavailable",
                "reason": "Could not resolve coordinates from location text",
                "location_text": location_text,
                "source": "Census Geocoder + CDC SVI 2022"
            }

        lat = coords_info["lat"]
        lon = coords_info["lon"]
        geo = self._census_tract_for_coordinates(lat, lon)
        if not geo:
            return {
                "status": "unavailable",
                "reason": "Census geocoder did not return a tract",
                "location_text": location_text,
                "coordinates": {"lat": lat, "lon": lon},
                "source": "Census Geocoder + CDC SVI 2022"
            }

        tract_geoid = str(geo.get("GEOID", ""))
        svi_row = self._load_svi_index().get(tract_geoid)
        if not svi_row:
            return {
                "status": "unavailable",
                "reason": f"No CDC SVI row found for tract {tract_geoid}",
                "location_text": location_text,
                "coordinates": {"lat": lat, "lon": lon},
                "tract_geoid": tract_geoid,
                "source": "Census Geocoder + CDC SVI 2022"
            }

        approximate = coords_info.get("source") != "exact_address"
        overall_svi = self._to_float(svi_row.get("RPL_THEMES"))

        return {
            "status": "resolved_approximate" if approximate else "resolved_exact",
            "approximate": approximate,
            "location_text": location_text,
            "resolved_location": coords_info.get("resolved_location"),
            "lookup_method": coords_info.get("source"),
            "coordinates": {"lat": lat, "lon": lon},
            "tract_geoid": tract_geoid,
            "county_fips": str(geo.get("COUNTY", "")),
            "county_name": str(svi_row.get("COUNTY", "")),
            "state_abbr": str(svi_row.get("ST_ABBR", "")),
            "state_name": str(svi_row.get("STATE", "")),
            "location_label": str(svi_row.get("LOCATION", "")),
            "population": self._to_int(svi_row.get("E_TOTPOP")),
            "poverty_pct": self._to_float(svi_row.get("EP_POV150") or svi_row.get("EP_POV")),
            "limited_english_pct": self._to_float(svi_row.get("EP_LIMENG")),
            "older_adults_pct": self._to_float(svi_row.get("EP_AGE65")),
            "overall_svi": overall_svi,
            "theme_scores": {
                "theme1": self._to_float(svi_row.get("RPL_THEME1")),
                "theme2": self._to_float(svi_row.get("RPL_THEME2")),
                "theme3": self._to_float(svi_row.get("RPL_THEME3")),
                "theme4": self._to_float(svi_row.get("RPL_THEME4")),
            },
            "source": "CDC Social Vulnerability Index 2022",
        }

    def _resolve_coordinates(self, location_text: str):
        """
        Resolve a location string to coordinates.

        Priority:
        1. Explicit coordinates in the text.
        2. Census geocoder exact address match.
        3. Small city-center proxy for supported demo cities.
        """
        coords = self._extract_coordinates(location_text)
        if coords:
            return {
                "lat": coords[0],
                "lon": coords[1],
                "source": "explicit_coordinates",
                "resolved_location": location_text,
            }

        address_match = self._census_address_match(location_text)
        if address_match:
            return address_match

        lowered = location_text.lower()
        for city_key, proxy in CITY_CENTER_FALLBACKS.items():
            if city_key in lowered:
                return {
                    "lat": proxy["lat"],
                    "lon": proxy["lon"],
                    "source": proxy["source"],
                    "resolved_location": city_key.title(),
                }

        return None

    def _extract_coordinates(self, text: str):
        pattern = re.compile(
            r"(?P<lat>-?\d{1,2}\.\d+)\s*,\s*(?P<lon>-?\d{1,3}\.\d+)"
        )
        match = pattern.search(text)
        if not match:
            return None
        return float(match.group("lat")), float(match.group("lon"))

    def _census_address_match(self, location_text: str) -> dict | None:
        try:
            response = requests.get(
                f"{CENSUS_GEOCODER_URL}/geographies/onelineaddress",
                params={
                    "address": location_text,
                    "benchmark": CENSUS_GEOCODER_BENCHMARK,
                    "vintage": CENSUS_GEOCODER_VINTAGE,
                    "format": "json",
                },
                timeout=12,
            )
            matches = response.json().get("result", {}).get("addressMatches", [])
            if not matches:
                return None

            best = matches[0]
            coords = best.get("coordinates", {})
            if "x" not in coords or "y" not in coords:
                return None

            return {
                "lat": float(coords["y"]),
                "lon": float(coords["x"]),
                "source": "exact_address",
                "resolved_location": best.get("matchedAddress", location_text),
            }
        except Exception as e:
            print(f"[BRIDGE] Census address geocoder failed: {e}")
            return None

    def _census_tract_for_coordinates(self, lat: float, lon: float) -> dict | None:
        try:
            response = requests.get(
                f"{CENSUS_GEOCODER_URL}/geographies/coordinates",
                params={
                    "x": lon,
                    "y": lat,
                    "benchmark": CENSUS_GEOCODER_BENCHMARK,
                    "vintage": CENSUS_GEOCODER_VINTAGE,
                    "format": "json",
                },
                timeout=12,
            )
            geographies = response.json().get("result", {}).get("geographies", {})
            tracts = geographies.get("Census Tracts", [])
            if not tracts:
                return None
            return tracts[0]
        except Exception as e:
            print(f"[BRIDGE] Census tract lookup failed: {e}")
            return None

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_svi_index() -> dict:
        index = {}
        try:
            with open(CDC_SVI_CSV, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    fips = str(row.get("FIPS", "")).strip()
                    if fips:
                        index[fips] = row
        except Exception as e:
            print(f"[BRIDGE] Failed to load CDC SVI CSV: {e}")
        return index

    @staticmethod
    def _to_float(value):
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value):
        try:
            if value in (None, ""):
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None

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
