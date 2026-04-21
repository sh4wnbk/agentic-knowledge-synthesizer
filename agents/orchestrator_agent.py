"""
agents/orchestrator_agent.py
Agent 2 — Reasoning & Planning Layer
Now includes explicit Regulatory Agency mapping to prevent acronym drift.
"""

from config import OHIO_BBOX, OKLAHOMA_BBOX

class OrchestratorAgent:

    # Oklahoma and Ohio induced seismicity routed to reasoning cluster.
    CLUSTER_MAP = {
        "induced_seismicity_ohio":      "reasoning_ohio",
        "induced_seismicity_oklahoma":  "reasoning_oklahoma",
        "induced_seismicity":           "reasoning",
        "natural_seismicity":           "coordination",
        "flooding":                     "coordination",
        "fire":                         "coordination",
        "default":                      "synthesis"
    }

    # NEW: Source of Truth for State Agencies
    AGENCY_MAP = {
        "reasoning_ohio":      "Ohio Department of Natural Resources (ODNR)",
        "reasoning_oklahoma":  "Oklahoma Corporation Commission (OCC)",
        "reasoning":           "State Emergency Management Agency",
        "coordination":        "Multi-Agency Coordination Center (MACC)",
        "default":             "Local Emergency Management"
    }

    AGENCY_ROUTING = {
        "reasoning_ohio": {
            "primary_regulatory": {
                "name": "Ohio Department of Natural Resources (ODNR)",
                "role": "Disposal well operational status; TLS monitoring trigger",
                "tier": 1,
            },
            "federal_emergency": {
                "name": "Federal Emergency Management Agency (FEMA)",
                "role": "Federal disaster coordination; aid eligibility assessment",
                "tier": 2,
            },
            "state_emergency": {
                "name": "Ohio Emergency Management Agency (Ohio EMA)",
                "role": "County-level coordination; shelter activation",
                "tier": 2,
            },
            "environmental": {
                "name": "Ohio Environmental Protection Agency (Ohio EPA)",
                "role": "Groundwater contamination assessment; well-water cloudiness",
                "tier": 2,
            },
            "local_emergency": {
                "name": "Local Fire and Law Enforcement",
                "role": "Structural assessment; gas leak evaluation; scene safety",
                "tier": 1,
            },
            "ngo": {
                "name": "American Red Cross",
                "role": "Shelter; immediate needs for displaced residents",
                "tier": 3,
                "hotline": "1-800-RED-CROSS",
            },
        },
        "reasoning_oklahoma": {
            "primary_regulatory": {
                "name": "Oklahoma Corporation Commission (OCC)",
                "role": "Injection well operational status; plug-back consideration",
                "tier": 1,
            },
            "federal_emergency": {
                "name": "Federal Emergency Management Agency (FEMA)",
                "role": "Federal disaster coordination; aid eligibility assessment",
                "tier": 2,
            },
            "state_emergency": {
                "name": "Oklahoma Office of Emergency Management (ODEM)",
                "role": "State coordination; shelter activation",
                "tier": 2,
            },
            "environmental": {
                "name": "Oklahoma Department of Environmental Quality (ODEQ)",
                "role": "Environmental hazard assessment; injection well impact",
                "tier": 2,
            },
            "local_emergency": {
                "name": "Local Fire and Law Enforcement",
                "role": "Structural assessment; gas leak evaluation; scene safety",
                "tier": 1,
            },
            "ngo": {
                "name": "American Red Cross",
                "role": "Shelter; immediate needs for displaced residents",
                "tier": 3,
                "hotline": "1-800-RED-CROSS",
            },
        },
    }

    CITATION_CHAIN = {
        "reasoning_ohio": (
            "Blackman (2025) — Mapping Disparate Risk: Induced Seismicity and Social Vulnerability "
            "[synthesizing Kim (2013); Keranen et al. (2014); Hincks et al. (2018); "
            "Skoumal et al. (2024)]"
        ),
        "reasoning_oklahoma": (
            "Blackman (2025) — Mapping Disparate Risk: Induced Seismicity and Social Vulnerability "
            "[synthesizing Keranen et al. (2014); Hincks et al. (2018); Skoumal et al. (2024)]"
        ),
        "reasoning": (
            "Blackman (2025) — Mapping Disparate Risk: Induced Seismicity and Social Vulnerability "
            "[synthesizing Keranen et al. (2014); Kim (2013); Hincks et al. (2018)]"
        ),
        "default": "Blackman (2025) — Mapping Disparate Risk: Induced Seismicity and Social Vulnerability",
    }

    def route(self, intent: dict) -> str:
        """
        Routes intent to specialist cluster and injects regulatory metadata.
        """
        crisis_type = intent.get("crisis_type") or "default"
        state       = intent.get("state")

        # Resolve induced seismicity to state-specific cluster
        if crisis_type == "induced_seismicity" and state:
            state_lower = state.lower()
            if "ohio" in state_lower or "oh" == state_lower:
                crisis_type = "induced_seismicity_ohio"
            elif "oklahoma" in state_lower or "ok" == state_lower:
                crisis_type = "induced_seismicity_oklahoma"

        cluster = self.CLUSTER_MAP.get(crisis_type, "synthesis")
        
        # NEW: Inject the specific agency name into the intent for the Synthesis Layer
        intent["regulatory_agency"] = self.AGENCY_MAP.get(cluster, self.AGENCY_MAP["default"])
        
        print(f"[ORCHESTRATOR] Routing '{crisis_type}' → {cluster} cluster")
        print(f"[ORCHESTRATOR] Assigned Agency: {intent['regulatory_agency']}")
        
        return cluster

    def get_agency_routing(self, cluster: str) -> dict:
        """Returns the tiered agency routing matrix for downstream use."""
        return self.AGENCY_ROUTING.get(cluster, {})

    def get_citation_chain(self, cluster: str) -> str:
        """Returns the scientific citation chain for downstream use."""
        return self.CITATION_CHAIN.get(cluster, self.CITATION_CHAIN["default"])

    def build_query(self, intent: dict, cluster: str) -> str:
        """
        Constructs the semantic RAG query string using the correct hazard model.
        """
        base = intent.get("raw_input", "")
        agency = intent.get("regulatory_agency", "relevant authorities")

        if cluster == "reasoning_ohio":
            return (
                f"Ohio induced seismicity disposal well proximity hazard. "
                f"Near-field pore pressure diffusion within 15 km of injection well. "
                f"Precambrian crystalline basement focal depth under 5 km. "
                f"High social vulnerability census tract emergency aid coordination. "
                f"{agency} Traffic Light System monitoring. {base}"
            )
        elif cluster == "reasoning_oklahoma":
            return (
                f"Oklahoma induced seismicity inter-agency response. "
                f"Oklahoma Corporation Commission OCC injection well plug-back Tier 1 notification. "
                f"Oklahoma Department of Environmental Quality ODEQ hazard assessment. "
                f"Oklahoma Office of Emergency Management ODEM shelter activation. "
                f"High social vulnerability SVI census tract emergency aid coordination. "
                f"HHS emPOWER electricity-dependent Medicare beneficiaries. "
                f"{agency} regulatory response. {base}"
            )
        # ... (rest of the build_query method remains the same) ...
        elif cluster == "reasoning":
            return f"Induced seismicity disposal well earthquake crisis. {base}"
        elif cluster == "coordination":
            return f"Multi-agency coordination emergency. {base}"
        else:
            return f"Emergency aid resources available. {base}"

    def get_bbox(self, cluster: str) -> dict:
        if cluster == "reasoning_ohio":
            return OHIO_BBOX
        elif cluster == "reasoning_oklahoma":
            return OKLAHOMA_BBOX
        else:
            return {}