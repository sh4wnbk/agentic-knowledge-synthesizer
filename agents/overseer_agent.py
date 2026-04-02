"""
agents/overseer_agent.py
Agent 5 — Governance Layer
Three hooks. Proactive, not reactive.
Intercepts before delivery. Retries with amended context.
Triggers honest fallback when retry budget is exhausted.
Key decision: validated against source, or fallback?
"""

from governance.audit_log import AuditLog
from config import CONFIDENCE_THRESHOLD, CITATION_ALIGN_THRESHOLD
import re


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

        This is where beam search candidates are evaluated:
        the candidate with the highest citation alignment score
        is selected — not the highest-probability token sequence.
        """
        if not citation or not output:
            self.log.record(
                "pre_delivery_check",
                {"output_len": len(output), "citation": citation},
                False,
                "Missing output or citation"
            )
            return False, 0.0

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
            # Fallback: check if output has factual content
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
