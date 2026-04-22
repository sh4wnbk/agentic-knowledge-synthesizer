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
from governance.external_harmonization import (
    merge_external_sources,
    normalize_fema_declarations,
    normalize_ifrc_events,
)
from config import (
    CENSUS_GEOCODER_BENCHMARK,
    CENSUS_GEOCODER_URL,
    CENSUS_GEOCODER_VINTAGE,
    CDC_SVI_CSV,
    EMPOWER_JSON,
    TRI_FACILITIES_JSON,
    SEISMIC_MIN_MAGNITUDE,
    USGS_API_URL,
)


CITY_CENTER_FALLBACKS = {
    "youngstown, oh": {"lat": 41.0998,  "lon": -80.6495,  "source": "city_center_proxy"},
    "warren, oh":     {"lat": 41.2375,  "lon": -80.8184,  "source": "city_center_proxy"},
    "niles, oh":      {"lat": 41.1853,  "lon": -80.7695,  "source": "city_center_proxy"},
    "canfield, oh":   {"lat": 41.0270,  "lon": -80.7623,  "source": "city_center_proxy"},
    "sebring, oh":    {"lat": 40.9248,  "lon": -81.0176,  "source": "city_center_proxy"},
    "lisbon, oh":     {"lat": 40.7720,  "lon": -80.7659,  "source": "city_center_proxy"},
    "salem, oh":      {"lat": 40.9020,  "lon": -80.8598,  "source": "city_center_proxy"},
    "columbiana, oh": {"lat": 40.8865,  "lon": -80.6912,  "source": "city_center_proxy"},
    "girard, oh":     {"lat": 41.1559,  "lon": -80.7023,  "source": "city_center_proxy"},
    "hubbard, oh":    {"lat": 41.1570,  "lon": -80.5701,  "source": "city_center_proxy"},
    "tulsa, ok":        {"lat": 36.15398, "lon": -95.99277, "source": "city_center_proxy"},
    "cushing, ok":      {"lat": 35.9851,  "lon": -96.7670,  "source": "city_center_proxy"},
    "stillwater, ok":   {"lat": 36.1156,  "lon": -97.0584,  "source": "city_center_proxy"},
    "oklahoma city, ok":{"lat": 35.4676,  "lon": -97.5164,  "source": "city_center_proxy"},
    "norman, ok":       {"lat": 35.2226,  "lon": -97.4395,  "source": "city_center_proxy"},
    "enid, ok":         {"lat": 36.3956,  "lon": -97.8784,  "source": "city_center_proxy"},
    "ardmore, ok":      {"lat": 34.1743,  "lon": -97.1436,  "source": "city_center_proxy"},
    "lawton, ok":       {"lat": 34.6036,  "lon": -98.3959,  "source": "city_center_proxy"},
    "edmond, ok":       {"lat": 35.6528,  "lon": -97.4781,  "source": "city_center_proxy"},
    "ponca city, ok":   {"lat": 36.7070,  "lon": -97.0856,  "source": "city_center_proxy"},
    "pawnee, ok":       {"lat": 36.3395,  "lon": -96.8003,  "source": "city_center_proxy"},
    "prague, ok":     {"lat": 35.4887,  "lon": -96.6842,  "source": "city_center_proxy"},
    "crescent, ok":   {"lat": 35.9539,  "lon": -97.5934,  "source": "city_center_proxy"},
    "fairview, ok":   {"lat": 36.2695,  "lon": -98.4748,  "source": "city_center_proxy"},
    "guthrie, ok":    {"lat": 35.8789,  "lon": -97.4253,  "source": "city_center_proxy"},
    "shawnee, ok":    {"lat": 35.3273,  "lon": -96.9253,  "source": "city_center_proxy"},
    "ada, ok":        {"lat": 34.7748,  "lon": -96.6783,  "source": "city_center_proxy"},
    "atoka, ok":      {"lat": 34.3859,  "lon": -96.1281,  "source": "city_center_proxy"},
    "duncan, ok":     {"lat": 34.5023,  "lon": -97.9578,  "source": "city_center_proxy"},
    "chickasha, ok":  {"lat": 35.0523,  "lon": -97.9370,  "source": "city_center_proxy"},
}


class DataBridgeAgent:

    def fetch(
        self,
        intent: dict,
        retrieval: dict,
        bbox: dict = None,
        agency_routing: dict = None,
    ) -> dict:
        """
        Fetches live data after RAG retrieval.
        bbox: geographic bounding box from Orchestrator.get_bbox()
              constrains USGS query to the relevant region.
        agency_routing: tiered routing matrix from Orchestrator.get_agency_routing()
        """
        svi_lookup = self._lookup_svi(intent)

        # Prefer a tight proximity bbox over the coarse state-level bbox.
        # When the incident location resolves to coordinates, constrain USGS
        # to ±1.5° (~100–150 km) so distant state events aren't misattributed.
        incident_coords = svi_lookup.get("coordinates")
        if incident_coords and incident_coords.get("lat") and incident_coords.get("lon"):
            usgs_bbox = self._proximity_bbox(incident_coords["lat"], incident_coords["lon"])
        else:
            usgs_bbox = bbox  # State-level fallback when coordinates unavailable

        # HHS emPOWER — electricity-dependent Medicare beneficiaries by county FIPS
        # tract_geoid[:5] is state FIPS (2) + county FIPS (3) = full 5-digit county FIPS
        county_fips = svi_lookup.get("tract_geoid", "")[:5]
        empower_data = self._fetch_empower(county_fips)

        # EPA TRI — hazmat facilities within tight incident bbox (±0.25° ≈ 25 km)
        # Deliberately tighter than USGS bbox so tier promotion only fires for
        # facilities genuinely proximate to the incident, not regionally co-located.
        if incident_coords and incident_coords.get("lat") and incident_coords.get("lon"):
            tri_bbox = self._proximity_bbox(incident_coords["lat"], incident_coords["lon"], radius_deg=0.25)
        else:
            tri_bbox = usgs_bbox or bbox
        epa_tri = self._fetch_epa_tri(tri_bbox)

        # Conditional EPA tier promotion: TRI facilities → environmental agency → Tier 1
        if epa_tri.get("hazmat_detected"):
            effective_routing = self._promote_epa_tier(agency_routing)
        else:
            effective_routing = agency_routing

        return {
            "usgs_live":      self._fetch_usgs_live(usgs_bbox, incident_coords=incident_coords),
            "fema_resources": self._fetch_fema(intent),
            "ngo_resources":  self._fetch_ngo(intent, agency_routing),
            "agency_routing": self._build_agency_brief(effective_routing),
            "external_operational_picture": self._build_external_operational_picture(
                intent,
                svi_lookup,
            ),
            "svi_lookup":     svi_lookup,
            "svi_data": {
                "svi_score": svi_lookup.get("overall_svi"),
                "tract_name": svi_lookup.get("location_label") or svi_lookup.get("tract_geoid", ""),
                "tract_geoid": svi_lookup.get("tract_geoid"),
                "state_abbr": svi_lookup.get("state_abbr"),
                "county_name": svi_lookup.get("county_name"),
                "approximate": svi_lookup.get("approximate", False),
            },
            "empower_data":   empower_data,
            "epa_tri":        epa_tri,
            "legal_scope_ok": self._verify_legal_scope(intent)
        }

    def _build_external_operational_picture(self, intent: dict, svi_lookup: dict) -> dict:
        """
        Harmonized external operations context.
        Merges FEMA declarations and IFRC events into one ranked payload.
        """
        try:
            fema_raw = self._fetch_fema_open_data()
            ifrc_raw = self._fetch_ifrc_go_data()
            fema_events = normalize_fema_declarations(fema_raw)
            ifrc_events = normalize_ifrc_events(ifrc_raw)
            return merge_external_sources(
                fema_events=fema_events,
                ifrc_events=ifrc_events,
                state_abbr=svi_lookup.get("state_abbr"),
                crisis_type=intent.get("crisis_type"),
                country_hint="US",
            )
        except Exception as e:
            print(f"[BRIDGE] External operational merge failed: {e}")
            return {
                "status": "unavailable",
                "reason": "External harmonization failed",
                "sources": {"fema_count": 0, "ifrc_count": 0},
                "top_events": [],
            }

    def _fetch_fema_open_data(self) -> dict:
        try:
            r = requests.get(
                "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
                params={"$top": 25},
                timeout=12,
            )
            return r.json() if r.ok else {}
        except Exception as e:
            print(f"[BRIDGE] FEMA Open API fetch failed: {e}")
            return {}

    def _fetch_ifrc_go_data(self) -> dict:
        try:
            r = requests.get(
                "https://goadmin.ifrc.org/api/v2/event/",
                params={"limit": 25},
                timeout=12,
            )
            return r.json() if r.ok else {}
        except Exception as e:
            print(f"[BRIDGE] IFRC GO API fetch failed: {e}")
            return {}

    def _build_agency_brief(self, agency_routing: dict = None) -> dict:
        """Groups the routing matrix into dispatcher-friendly tiers."""
        if not agency_routing:
            return {"note": "Agency routing unavailable — contact local emergency services"}

        tier1, tier2, tier3 = [], [], []

        for agency in agency_routing.values():
            tier = agency.get("tier", 3)
            entry = {
                "name": agency.get("name"),
                "role": agency.get("role"),
            }
            if agency.get("hotline"):
                entry["hotline"] = agency.get("hotline")

            if tier == 1:
                tier1.append(entry)
            elif tier == 2:
                tier2.append(entry)
            else:
                tier3.append(entry)

        return {
            "tier_1_immediate": tier1,
            "tier_2_within_hour": tier2,
            "tier_3_as_warranted": tier3,
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
            "source":           "CDC Social Vulnerability Index 2022",
            "verification_url": f"https://data.census.gov/table?g=1400000US{tract_geoid}",
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
        # Load only Ohio (39) and Oklahoma (40) tracts, only the columns the
        # pipeline actually reads. Reduces memory from ~400 MB to ~5 MB.
        KEEP_COLS = {
            "FIPS", "ST_ABBR", "STATE", "COUNTY", "LOCATION",
            "RPL_THEMES", "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4",
            "E_TOTPOP", "EP_POV150", "EP_POV", "EP_LIMENG", "EP_AGE65",
        }
        TARGET_STATES = {"OH", "OK"}
        index = {}
        try:
            with open(CDC_SVI_CSV, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("ST_ABBR", "") not in TARGET_STATES:
                        continue
                    fips = str(row.get("FIPS", "")).strip()
                    if fips:
                        index[fips] = {k: v for k, v in row.items() if k in KEEP_COLS}
        except Exception as e:
            print(f"[BRIDGE] Failed to load CDC SVI CSV: {e}")
        print(f"[BRIDGE] SVI index loaded: {len(index)} tracts (OH + OK only)")
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

    @staticmethod
    def _proximity_bbox(lat: float, lon: float, radius_deg: float = 1.5) -> dict:
        """
        Tight bounding box centered on incident coordinates.
        radius_deg=1.5 ≈ 100–150 km — captures near-field induced seismicity
        without the state-level noise that causes misattribution.
        """
        return {
            "minlatitude":  round(lat - radius_deg, 4),
            "maxlatitude":  round(lat + radius_deg, 4),
            "minlongitude": round(lon - radius_deg, 4),
            "maxlongitude": round(lon + radius_deg, 4),
        }

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance in km between two lat/lon points."""
        import math
        R = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_empower_index() -> dict:
        try:
            import json as _json
            with open(EMPOWER_JSON, encoding="utf-8") as f:
                return _json.load(f)
        except Exception as e:
            print(f"[BRIDGE] Failed to load emPOWER JSON: {e}")
            return {}

    def _fetch_empower(self, county_fips: str) -> dict:
        """
        HHS emPOWER — electricity-dependent Medicare beneficiaries by county FIPS.
        Served from local snapshot (data/empower_oh_ok.json) covering OH and OK.
        """
        if not county_fips:
            return {
                "status": "unavailable",
                "reason": "County FIPS not resolved from incident location",
                "source": "HHS emPOWER",
            }
        row = self._load_empower_index().get(county_fips)
        if not row:
            return {
                "status": "unavailable",
                "reason": f"No emPOWER record for FIPS {county_fips}",
                "source": "HHS emPOWER",
            }
        return {
            "county_fips":                county_fips,
            "county_name":                row.get("NAME"),
            "electricity_dependent_count": row.get("Power_Dependent_Devices_DME"),
            "ventilator_count":            row.get("Power_De_1"),
            "oxygen_count":                row.get("O2_Services_Any_DME"),
            "medicare_benes":              row.get("Medicare_Benes"),
            "source":                      "HHS emPOWER (ArcGIS, OH/OK snapshot)",
            "verification_url":            f"https://empowermap.hhs.gov/#county/{county_fips}",
        }

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_tri_index() -> list:
        try:
            import json as _json
            with open(TRI_FACILITIES_JSON, encoding="utf-8") as f:
                return _json.load(f)
        except Exception as e:
            print(f"[BRIDGE] Failed to load TRI facilities JSON: {e}")
            return []

    def _fetch_epa_tri(self, bbox: dict = None) -> dict:
        """
        EPA TRI — active facilities within the incident bounding box.
        Served from local snapshot (data/tri_facilities_oh_ok.json).
        bbox filter applied in-memory; no network call at runtime.
        """
        if not bbox:
            return {
                "hazmat_detected": False,
                "facility_count":  0,
                "facilities":      [],
                "source":          "EPA TRI (OH/OK snapshot)",
            }
        min_lat = bbox.get("minlatitude")
        max_lat = bbox.get("maxlatitude")
        min_lon = bbox.get("minlongitude")
        max_lon = bbox.get("maxlongitude")

        matches = [
            f for f in self._load_tri_index()
            if min_lat <= f["lat"] <= max_lat
            and min_lon <= f["lon"] <= max_lon
        ]
        return {
            "facility_count":  len(matches),
            "hazmat_detected": len(matches) > 0,
            "facilities":      [
                {"name": f["name"], "city": f["city"], "lat": f["lat"], "lon": f["lon"]}
                for f in matches[:10]
            ],
            "source":          "EPA TRI (OH/OK snapshot)",
            "verification_url": "https://www.epa.gov/toxics-release-inventory-tri-program",
        }

    @staticmethod
    def _promote_epa_tier(agency_routing: dict) -> dict:
        """
        Returns a copy of agency_routing with the 'environmental' agency promoted
        from Tier 2 to Tier 1 when TRI hazmat facilities are detected in the bbox.
        Never mutates the original dict.
        """
        import copy
        if not agency_routing or "environmental" not in agency_routing:
            return agency_routing if agency_routing else {}
        promoted = copy.deepcopy(agency_routing)
        env = promoted["environmental"]
        env["tier"] = 1
        env["role"] = "\u26a0 COMPOUND HAZMAT RISK \u2014 " + env.get("role", "")
        return promoted

    def _fetch_usgs_live(self, bbox: dict = None, incident_coords: dict = None) -> dict:
        """
        Live USGS feed — M >= threshold events.
        Prefers a tight proximity bbox centered on incident coordinates over
        the coarse state-level bbox to prevent misattribution across counties.
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

            latest   = features[0]["properties"]
            coords   = features[0].get("geometry", {}).get("coordinates", [])
            event_id = features[0].get("id", "")

            distance_km = None
            geographic_note = None
            if incident_coords and len(coords) >= 2:
                event_lon, event_lat = coords[0], coords[1]
                distance_km = self._haversine_km(
                    incident_coords["lat"], incident_coords["lon"],
                    event_lat, event_lon,
                )
                if distance_km < 30:
                    geographic_note = f"Co-located: nearest event {round(distance_km, 1)} km from incident"
                elif distance_km < 50:
                    geographic_note = f"Nearest regional event ({round(distance_km, 1)} km from incident)"
                else:
                    geographic_note = (
                        f"No USGS-verified seismic activity at reported location. "
                        f"Nearest catalogued event: {round(distance_km, 1)} km from incident. "
                        f"Reported incident may precede USGS catalogue update "
                        f"(typical lag: 5\u201315 min) or location may require correction."
                    )

            return {
                "status":                   "HAZARD DETECTED: SEISMIC EVENT CONFIRMED",
                "latest_event":             latest.get("place"),
                "magnitude":                latest.get("mag"),
                "depth_km":                 coords[2] if len(coords) > 2 else "unknown",
                "region_scope":             "regional",
                "event_count":              len(features),
                "event_id":                 event_id,
                "distance_from_incident_km": distance_km,
                "geographic_note":          geographic_note,
                "verification_url": (
                    f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}/executive"
                    if event_id else None
                ),
                "source": "USGS Earthquake Hazards API (real-time)"
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

    def _fetch_ngo(self, intent: dict, agency_routing: dict = None) -> dict:
        # Production: Red Cross API, Municipal Housing registry.
        if agency_routing and "ngo" in agency_routing:
            ngo = agency_routing["ngo"]
            return {
                "name":    ngo.get("name", "American Red Cross"),
                "role":    ngo.get("role", "Shelter and immediate needs"),
                "hotline": ngo.get("hotline", "1-800-RED-CROSS"),
                "source":  "Agency routing matrix",
            }
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
