"""
agents/overseer_agent.py
Agent 5 — Governance Layer
Three hooks. Proactive, not reactive.
Intercepts before delivery. Retries with amended context.
Triggers honest fallback when retry budget is exhausted.
Key decision: validated against source, or fallback?
"""

import re
from governance.audit_log import AuditLog
from config import CONFIDENCE_THRESHOLD, CITATION_ALIGN_THRESHOLD


# ── Unfilled template detection ───────────────────────────
# Granite occasionally returns prompt scaffolding rather than
# completing the instruction. These signals identify outputs
# that expose the prompt structure to the citizen — a distinct
# failure mode from citation mismatch. Neither should reach delivery.
UNFILLED_TEMPLATE_SIGNALS = [
    "1 sentence specifying",
    "2 sentences specifying",
    "insert ",
    "[your ",
    "[action",
    "[insert",
    "[describe",
    "fill in",
    "fill out",
    "placeholder",
    "<action>",
    "<insert>",
    "specifying the immediate action",
    "specifying the next step",
    "summarize key",
    "from the relevant",
]

class OverseerAgent:

    def __init__(self):
        self.log = AuditLog()

    # ── HOOK 1: Input Audit ───────────────────────────────────
    def input_audit(self, intent: dict) -> bool:
        """
        Earliest possible intervention.
        Catches structuring failures before reasoning begins.
        """
        passed = intent.get("is_complete", False)
        reason = "Intent complete" if passed else "Location or crisis type missing"
        self.log.record("input_audit", intent, passed, reason)
        return passed

    # ── HOOK 2: Retrieval Audit ───────────────────────────────
    def retrieval_audit(self, retrieval: dict) -> bool:
        """
        Monitors what the knowledge store returns.
        Low-confidence retrieval does not proceed to reasoning.
        """
        confidence = retrieval.get("confidence", 0.0)
        passed     = confidence >= CONFIDENCE_THRESHOLD
        reason     = (f"Confidence {confidence:.2f} >= {CONFIDENCE_THRESHOLD}"
                      if passed else
                      f"Confidence {confidence:.2f} below threshold {CONFIDENCE_THRESHOLD}")
        self.log.record("retrieval_audit", {"confidence": confidence}, passed, reason)
        return passed

    # ── HOOK 3: Pre-Delivery Check ────────────────────────────
    def pre_delivery_check(self, output: str, citation: str) -> tuple:
        """
        Cross-validates the generated output against its cited source.
        The last gate before the citizen receives anything.

        Returns (passed: bool, citation_score: float).

        Two sequential checks:
        1. Unfilled template detection — catches prompt artifacts
           that expose scaffolding to the citizen.
        2. Citation alignment scoring — catches source mismatches.

        Both must pass. A prompt artifact that scores 1.00 on
        citation alignment still fails — the Overseer rejects it.
        """
        if not citation or not output:
            self.log.record(
                "pre_delivery_check",
                {"output_len": len(output) if output else 0,
                 "citation": citation},
                False,
                "Missing output or citation"
            )
            return False, 0.0

        # ── Check 1: Unfilled template detection ──────────────
        if self._has_unfilled_template(output):
            self.log.record(
                "pre_delivery_check",
                {"citation": citation},
                False,
                "Prompt artifact detected — output contains unfilled template"
            )
            return False, 0.0

        # ── Check 2: Citation alignment ───────────────────────
        score  = self._citation_alignment_score(output, citation)
        passed = score >= CITATION_ALIGN_THRESHOLD
        reason = (f"Citation alignment {score:.2f} >= {CITATION_ALIGN_THRESHOLD}"
                  if passed else
                  f"Citation alignment {score:.2f} below threshold")
        self.log.record(
            "pre_delivery_check",
            {"citation_score": score, "citation": citation},
            passed,
            reason
        )
        return passed, score

    def _has_unfilled_template(self, output: str) -> bool:
        """
        Detects prompt scaffolding in the generated output.
        Granite occasionally returns the instruction rather than
        completing it — exposing the prompt structure to the citizen.
        This is a distinct failure mode from citation mismatch:
        a factually grounded response can still fail this check
        if it contains an unfilled instruction fragment.
        """
        output_lower = output.lower()
        for signal in UNFILLED_TEMPLATE_SIGNALS:
            if signal.lower() in output_lower:
                return True
        return False

    def _citation_alignment_score(self, output: str, citation: str) -> float:
        """
        Scores how well the output aligns with its cited sources.

        Prototype: keyword overlap between output and citation string.
        Production: semantic similarity via watsonx.ai embedding comparison
        between generated text and the retrieved source chunks.

        This is the selection criterion for beam search candidates —
        the beam with the highest alignment score wins,
        not the beam with the highest token probability.
        """
        if not citation:
            return 0.0

        # Extract meaningful terms from citation
        citation_terms = set(
            re.findall(r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b', citation)
        )
        output_lower = output.lower()

        if not citation_terms:
            return 0.65 if len(output) > 50 else 0.0

        matched = sum(
            1 for term in citation_terms
            if term.lower() in output_lower
        )
        return round(matched / len(citation_terms), 3)

    def get_audit_log(self) -> list:
        return self.log.to_list()

    def export_audit_log(self, path: str = "audit_log.json"):
        self.log.export(path)
