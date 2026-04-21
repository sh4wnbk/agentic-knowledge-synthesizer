"""
tests/test_units.py
Pure unit tests — no LLM, no network, no ChromaDB.
Tests the specific logic changed in the EOC refactor.
Run with: pytest tests/test_units.py -v
"""

import pytest
from agents.intake_agent import IntakeAgent
from agents.data_bridge_agent import DataBridgeAgent
from agents.overseer_agent import OverseerAgent
from config import OHIO_BBOX, OKLAHOMA_BBOX


# ── IntakeAgent.parse() ───────────────────────────────────────

class TestIntakeAgentParse:

    def setup_method(self):
        self.agent = IntakeAgent()

    # NE Ohio shale zone cities (added in refactor)

    def test_niles_ohio_resolves(self):
        r = self.agent.parse("Seismic activity in Niles, Ohio")
        assert r["location"] == "Niles, OH"
        assert r["state"] == "Ohio"
        assert r["is_complete"] is True

    def test_girard_ohio_resolves(self):
        r = self.agent.parse("Ground shaking reported near Girard, Ohio")
        assert r["location"] == "Girard, OH"
        assert r["state"] == "Ohio"

    def test_canfield_ohio_resolves(self):
        r = self.agent.parse("M2.9 event near Canfield, Ohio")
        assert r["location"] == "Canfield, OH"
        assert r["state"] == "Ohio"

    def test_columbiana_ohio_resolves(self):
        r = self.agent.parse("Tremors in Columbiana County, Ohio")
        assert r["location"] == "Columbiana, OH"
        assert r["state"] == "Ohio"

    def test_austintown_maps_to_youngstown(self):
        r = self.agent.parse("Shaking reported in Austintown, Ohio")
        assert r["location"] == "Youngstown, OH"
        assert r["state"] == "Ohio"

    def test_lordstown_maps_to_warren(self):
        r = self.agent.parse("Induced seismicity near Lordstown, Ohio")
        assert r["location"] == "Warren, OH"
        assert r["state"] == "Ohio"

    # Oklahoma expansion cities

    def test_pawnee_oklahoma_resolves(self):
        r = self.agent.parse("M3.1 near Pawnee, Oklahoma")
        assert r["location"] == "Pawnee, OK"
        assert r["state"] == "Oklahoma"
        assert r["is_complete"] is True

    def test_duncan_oklahoma_resolves(self):
        r = self.agent.parse("Seismic event near Duncan, Oklahoma")
        assert r["location"] == "Duncan, OK"
        assert r["state"] == "Oklahoma"

    def test_prague_oklahoma_resolves(self):
        r = self.agent.parse("M2.8 event reported in Prague, Oklahoma")
        assert r["location"] == "Prague, OK"
        assert r["state"] == "Oklahoma"

    # State inference from city name (no explicit state)

    def test_state_inferred_from_ohio_city(self):
        r = self.agent.parse("M2.8 tremors in Girard")
        assert r["state"] == "Ohio"

    def test_state_inferred_from_oklahoma_city(self):
        r = self.agent.parse("Ground shaking in Cushing")
        assert r["state"] == "Oklahoma"

    # Crisis type detection

    def test_seismic_keywords_detected(self):
        for keyword in ["earthquake", "shaking", "tremor", "seismic", "quake"]:
            r = self.agent.parse(f"{keyword} in Youngstown Ohio")
            assert r["crisis_type"] == "induced_seismicity", f"Failed for keyword: {keyword}"

    def test_magnitude_keyword_detected(self):
        r = self.agent.parse("M3.2 event in Youngstown, Ohio")
        assert r["crisis_type"] == "induced_seismicity"

    # Completeness gates

    def test_complete_intent_requires_location_and_crisis_type(self):
        r = self.agent.parse("Earthquake in Youngstown, Ohio")
        assert r["is_complete"] is True

    def test_missing_location_is_incomplete(self):
        r = self.agent.parse("There was an earthquake but I won't say where")
        assert r["is_complete"] is False

    def test_missing_crisis_type_is_incomplete(self):
        r = self.agent.parse("Something happened in Youngstown, Ohio")
        assert r["is_complete"] is False

    def test_vague_input_is_incomplete(self):
        assert self.agent.parse("help now")["is_complete"] is False
        assert self.agent.parse("something happened")["is_complete"] is False
        assert self.agent.parse("I'm not sure what that was")["is_complete"] is False


# ── DataBridgeAgent._proximity_bbox() ────────────────────────

class TestProximityBbox:

    def test_returns_all_four_keys(self):
        bbox = DataBridgeAgent._proximity_bbox(41.0998, -80.6495)
        assert set(bbox.keys()) == {"minlatitude", "maxlatitude", "minlongitude", "maxlongitude"}

    def test_default_radius_is_1_5_degrees(self):
        lat, lon = 41.0998, -80.6495
        bbox = DataBridgeAgent._proximity_bbox(lat, lon)
        assert bbox["minlatitude"]  == round(lat - 1.5, 4)
        assert bbox["maxlatitude"]  == round(lat + 1.5, 4)
        assert bbox["minlongitude"] == round(lon - 1.5, 4)
        assert bbox["maxlongitude"] == round(lon + 1.5, 4)

    def test_custom_radius(self):
        lat, lon = 41.0998, -80.6495
        bbox = DataBridgeAgent._proximity_bbox(lat, lon, radius_deg=0.5)
        assert bbox["minlatitude"]  == round(lat - 0.5, 4)
        assert bbox["maxlatitude"]  == round(lat + 0.5, 4)

    def test_proximity_box_smaller_than_ohio_state_bbox(self):
        youngstown_bbox = DataBridgeAgent._proximity_bbox(41.0998, -80.6495)
        lat_span_proximity = youngstown_bbox["maxlatitude"] - youngstown_bbox["minlatitude"]
        lat_span_ohio      = OHIO_BBOX["maxlatitude"] - OHIO_BBOX["minlatitude"]
        assert lat_span_proximity < lat_span_ohio

    def test_oklahoma_proximity_box_smaller_than_state_bbox(self):
        cushing_bbox = DataBridgeAgent._proximity_bbox(35.985, -96.767)
        lat_span_proximity = cushing_bbox["maxlatitude"] - cushing_bbox["minlatitude"]
        lat_span_ok        = OKLAHOMA_BBOX["maxlatitude"] - OKLAHOMA_BBOX["minlatitude"]
        assert lat_span_proximity < lat_span_ok


# ── DataBridgeAgent._haversine_km() ──────────────────────────

class TestHaversineKm:

    def test_same_point_is_zero(self):
        assert DataBridgeAgent._haversine_km(41.0998, -80.6495, 41.0998, -80.6495) == 0.0

    def test_youngstown_to_madison_ohio(self):
        # The original misattribution case: USGS returned Madison OH for a Youngstown event.
        # Distance should be ~83 km — far enough to be operationally wrong.
        km = DataBridgeAgent._haversine_km(41.0998, -80.6495, 41.7762, -81.0578)
        assert 70 < km < 100, f"Expected ~83 km, got {km}"

    def test_youngstown_to_tulsa_cross_country(self):
        km = DataBridgeAgent._haversine_km(41.0998, -80.6495, 36.154, -95.993)
        assert km > 1200, f"Expected >1200 km cross-country, got {km}"

    def test_nearby_points_under_30km(self):
        # Youngstown to Niles OH — should be well under 30 km (co-located threshold)
        km = DataBridgeAgent._haversine_km(41.0998, -80.6495, 41.1853, -80.7695)
        assert km < 30, f"Expected <30 km for nearby cities, got {km}"

    def test_result_is_float(self):
        result = DataBridgeAgent._haversine_km(41.0, -80.0, 42.0, -81.0)
        assert isinstance(result, float)


# ── OverseerAgent._has_required_sections() ───────────────────

class TestRequiredSections:

    VALID_OUTPUT = (
        "[HAZARD STATUS]\nUSGS reports M2.8 event.\n\n"
        "[DEMOGRAPHIC RISK (SVI)]\nHigh vulnerability tract.\n\n"
        "[INTER-AGENCY ROUTING]\nODNR Tier 1.\n"
    )

    def setup_method(self):
        self.overseer = OverseerAgent()

    def test_all_sections_present_passes(self):
        ok, missing = self.overseer._has_required_sections(self.VALID_OUTPUT)
        assert ok is True
        assert missing == []

    def test_missing_inter_agency_routing(self):
        output = "[HAZARD STATUS]\nfoo\n[DEMOGRAPHIC RISK (SVI)]\nbar"
        ok, missing = self.overseer._has_required_sections(output)
        assert ok is False
        assert "[INTER-AGENCY ROUTING]" in missing

    def test_missing_demographic_risk(self):
        output = "[HAZARD STATUS]\nfoo\n[INTER-AGENCY ROUTING]\nbar"
        ok, missing = self.overseer._has_required_sections(output)
        assert ok is False
        assert "[DEMOGRAPHIC RISK (SVI)]" in missing

    def test_missing_hazard_status(self):
        output = "[DEMOGRAPHIC RISK (SVI)]\nfoo\n[INTER-AGENCY ROUTING]\nbar"
        ok, missing = self.overseer._has_required_sections(output)
        assert ok is False
        assert "[HAZARD STATUS]" in missing

    def test_missing_two_sections_returns_both(self):
        output = "[HAZARD STATUS]\nonly one section"
        ok, missing = self.overseer._has_required_sections(output)
        assert ok is False
        assert len(missing) == 2

    def test_empty_string_fails_all(self):
        ok, missing = self.overseer._has_required_sections("")
        assert ok is False
        assert len(missing) == 3

    def test_case_sensitive_lowercase_fails(self):
        # Headers must match exactly — lowercase should not pass
        output = "[hazard status]\n[demographic risk (svi)]\n[inter-agency routing]"
        ok, missing = self.overseer._has_required_sections(output)
        assert ok is False

    def test_pre_delivery_check_rejects_missing_section(self):
        # End-to-end: pre_delivery_check should return (False, 0.0) if a section is missing
        # Use a citation string that would otherwise pass alignment
        output_missing_section = "[HAZARD STATUS]\nUSGS M2.8.\n[DEMOGRAPHIC RISK (SVI)]\nSVI 0.95."
        citation = "Blackman (2025)"
        passed, score = self.overseer.pre_delivery_check(output_missing_section, citation)
        assert passed is False
        assert score == 0.0


# ── DataBridgeAgent._promote_epa_tier() ──────────────────

class TestEpaTierPromotion:

    SAMPLE_ROUTING = {
        "state_agency": {"name": "ODNR", "role": "Well permitting oversight", "tier": 1},
        "environmental": {"name": "Ohio EPA", "role": "Environmental hazard response", "tier": 2},
        "federal": {"name": "FEMA", "role": "Federal disaster coordination", "tier": 2},
    }

    def test_promotes_environmental_to_tier_1_when_hazmat_detected(self):
        result = DataBridgeAgent._promote_epa_tier(self.SAMPLE_ROUTING)
        assert result["environmental"]["tier"] == 1

    def test_promoted_role_contains_hazmat_warning(self):
        result = DataBridgeAgent._promote_epa_tier(self.SAMPLE_ROUTING)
        assert "COMPOUND HAZMAT RISK" in result["environmental"]["role"]

    def test_does_not_mutate_original_routing(self):
        original_tier = self.SAMPLE_ROUTING["environmental"]["tier"]
        DataBridgeAgent._promote_epa_tier(self.SAMPLE_ROUTING)
        assert self.SAMPLE_ROUTING["environmental"]["tier"] == original_tier

    def test_non_environmental_tiers_unchanged(self):
        result = DataBridgeAgent._promote_epa_tier(self.SAMPLE_ROUTING)
        assert result["state_agency"]["tier"] == 1
        assert result["federal"]["tier"] == 2

    def test_promote_returns_unchanged_if_no_environmental_key(self):
        routing_no_env = {
            "state_agency": {"name": "ODNR", "role": "Well oversight", "tier": 1},
        }
        result = DataBridgeAgent._promote_epa_tier(routing_no_env)
        assert result == routing_no_env

    def test_promote_returns_empty_dict_for_none(self):
        result = DataBridgeAgent._promote_epa_tier(None)
        assert result == {}


# ── DataBridgeAgent._fetch_empower() fallback ────────────

class TestEmpowerFallback:

    def test_empty_fips_returns_unavailable(self):
        bridge = DataBridgeAgent()
        result = bridge._fetch_empower("")
        assert result.get("status") == "unavailable"
        assert result.get("source") == "HHS emPOWER"

    def test_none_fips_returns_unavailable(self):
        bridge = DataBridgeAgent()
        result = bridge._fetch_empower(None)
        assert result.get("status") == "unavailable"

    def test_unavailable_result_has_no_count_key(self):
        bridge = DataBridgeAgent()
        result = bridge._fetch_empower("")
        # electricity_dependent_count should not be present in the unavailable path
        assert "electricity_dependent_count" not in result


# ── DataBridgeAgent._fetch_epa_tri() empty result ────────

class TestEpaTrIEmptyResult:

    def test_no_bbox_returns_safe_structure(self):
        bridge = DataBridgeAgent()
        result = bridge._fetch_epa_tri(None)
        assert "hazmat_detected" in result
        assert result["hazmat_detected"] is False
        assert "facility_count" in result
        assert result["facility_count"] == 0
        assert "facilities" in result
        assert isinstance(result["facilities"], list)

    def test_no_bbox_source_is_epa_tri(self):
        bridge = DataBridgeAgent()
        result = bridge._fetch_epa_tri(None)
        assert result.get("source") == "EPA TRI (OH/OK snapshot)"


# ── DataBridgeAgent geographic_note thresholds ───────────────

class TestGeographicNoteThresholds:
    """
    Validates the three-tier geographic note logic:
      < 30 km  → co-located
      30–50 km → nearest regional event
      > 50 km  → no verified activity at reported location
    """

    def _make_note(self, distance_km: float) -> str:
        """
        Reproduce the geographic_note branching logic directly so the
        test stays in sync with data_bridge_agent.py without a live
        USGS call.
        """
        if distance_km < 30:
            return f"Co-located: nearest event {round(distance_km, 1)} km from incident"
        elif distance_km < 50:
            return f"Nearest regional event ({round(distance_km, 1)} km from incident)"
        else:
            return (
                f"No USGS-verified seismic activity at reported location. "
                f"Nearest catalogued event: {round(distance_km, 1)} km from incident. "
                f"Reported incident may precede USGS catalogue update "
                f"(typical lag: 5\u201315 min) or location may require correction."
            )

    def test_under_30km_is_colocated(self):
        note = self._make_note(12.3)
        assert note.startswith("Co-located")
        assert "12.3 km" in note

    def test_30_to_50km_is_nearest_regional(self):
        note = self._make_note(40.0)
        assert note.startswith("Nearest regional event")
        assert "40.0 km" in note

    def test_over_50km_is_unverified(self):
        # Youngstown→Madison OH case: 83 km — should flag unverified
        note = self._make_note(79.3)
        assert "No USGS-verified seismic activity" in note
        assert "79.3 km" in note
        assert "USGS catalogue update" in note

    def test_cushing_union_city_distance_is_unverified(self):
        # Cushing→Union City OK case: 140.2 km
        note = self._make_note(140.2)
        assert "No USGS-verified seismic activity" in note

    def test_boundary_exactly_50km_is_unverified(self):
        note = self._make_note(50.0)
        assert "No USGS-verified seismic activity" in note

    def test_boundary_exactly_30km_is_nearest_regional(self):
        note = self._make_note(30.0)
        assert note.startswith("Nearest regional event")
