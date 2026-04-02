"""
agents/orchestrator_agent.py
Agent 2 — Reasoning & Planning Layer
Routes structured intent to the correct specialist cluster.
Key decision: Coordination, Reasoning, or Synthesis cluster?
"""


class OrchestratorAgent:

    # Maps crisis type to specialist cluster.
    # Coordination: multi-agency data bridge required.
    # Reasoning:    seismic/SVI cross-reference required.
    # Synthesis:    single front-door, direct aid lookup.
    CLUSTER_MAP = {
        "induced_seismicity": "reasoning",
        "flooding":           "coordination",
        "fire":               "coordination",
        "default":            "synthesis"
    }

    def route(self, intent: dict) -> str:
        crisis_type = intent.get("crisis_type") or "default"
        cluster     = self.CLUSTER_MAP.get(crisis_type, "synthesis")
        print(f"[ORCHESTRATOR] Routing '{crisis_type}' → {cluster} cluster")
        return cluster

    def build_query(self, intent: dict, cluster: str) -> str:
        """
        Constructs the semantic query string for RAG retrieval.
        Cluster-aware — reasoning cluster queries emphasize
        seismic risk + vulnerability intersection.
        """
        base = intent.get("raw_input", "")

        if cluster == "reasoning":
            return (
                f"Induced seismicity earthquake crisis near disposal well. "
                f"High social vulnerability census tract. "
                f"Emergency aid coordination required. {base}"
            )
        elif cluster == "coordination":
            return (
                f"Multi-agency coordination emergency. "
                f"Federal state NGO data bridge required. {base}"
            )
        else:
            return f"Emergency aid resources available. {base}"
