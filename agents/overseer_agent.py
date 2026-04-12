"""
agents/overseer_agent.py
Agent 5 — Governance Layer
Three hooks. Proactive, not reactive.
Intercepts before delivery. Retries with amended context.
Triggers honest fallback when retry budget is exhausted.
Key decision: validated against source, or fallback?
"""

import re
import math
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
    "1 sentence advising",
    "2 sentences advising",
    "advising the dispatcher on next steps",
    "[assistant advice]",
    "engage local emergency services for immediate response",
]

class OverseerAgent:

    def __init__(self):
        self.log = AuditLog()
        self._embedder = None  # Lazy-loaded to avoid startup cost

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
    def pre_delivery_check(self, output: str, citation: str, context: str = "") -> tuple:
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
        # Prefer full retrieved context for semantic comparison;
        # fall back to citation string if context not provided.
        reference = context if context else citation
        score  = self._citation_alignment_score(output, reference)
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

    def _get_embedder(self):
        """Lazy-load the sentence transformer to avoid startup overhead."""
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        return self._embedder

    def _citation_alignment_score(self, output: str, reference: str) -> float:
        """
        Scores semantic alignment between generated output and retrieved
        source context using embedding cosine similarity.

        Replaces keyword overlap, which measured prompt compliance
        (did the output reproduce the citation string?) rather than
        factual grounding (does the output reflect what was retrieved?).

        Cosine similarity range with all-MiniLM-L6-v2:
          > 0.70  strong alignment
          0.50–0.70  moderate
          < 0.50  weak — likely hallucinated or off-topic
        """
        if not output or not reference:
            return 0.0
        try:
            embedder = self._get_embedder()
            vecs = embedder.encode([output, reference], convert_to_numpy=True)
            a, b = vecs[0], vecs[1]
            dot = float(sum(x * y for x, y in zip(a.tolist(), b.tolist())))
            norm_a = math.sqrt(sum(x * x for x in a.tolist()))
            norm_b = math.sqrt(sum(y * y for y in b.tolist()))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return round(max(0.0, dot / (norm_a * norm_b)), 3)
        except Exception as e:
            print(f"[OVERSEER] Embedding scoring failed: {e}")
            return 0.0

    def get_audit_log(self) -> list:
        return self.log.to_list()

    def export_audit_log(self, path: str = "audit_log.json"):
        self.log.export(path)
