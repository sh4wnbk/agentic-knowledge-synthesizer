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
                f"Oklahoma induced seismicity basin-wide injection hazard. "
                f"High-volume disposal well hydraulic connectivity crystalline basement. "
                f"Arbuckle Group injection seismogenic zone. "
                f"High social vulnerability census tract emergency aid coordination. "
                f"{agency} plug-back regulations. {base}"
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