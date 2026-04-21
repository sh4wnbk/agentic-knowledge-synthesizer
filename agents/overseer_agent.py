"""
agents/overseer_agent.py
Agent 5 — Governance Layer
Three hooks. Proactive, not reactive.
Intercepts before delivery. Retries with amended context.
Triggers honest fallback when retry budget is exhausted.
Key decision: validated against source, or fallback?
"""

import json
import re
import math
import time

import requests
from governance.audit_log import AuditLog
from config import (
    CITATION_ALIGN_THRESHOLD,
    CONFIDENCE_THRESHOLD,
    GRANITE_GUARDIAN_MODEL,
    GRANITE_GUARDIAN_THRESHOLD,
    USE_GRANITE_GUARDIAN,
    WATSONX_API_KEY,
    WATSONX_PROJECT_ID,
    WATSONX_URL,
)


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

REQUIRED_SECTIONS = [
    "[HAZARD STATUS]",
    "[DEMOGRAPHIC RISK (SVI)]",
    "[INTER-AGENCY ROUTING]",
]


class OverseerAgent:

    def __init__(self):
        self.log = AuditLog()
        self._embedder = None  # Lazy-loaded to avoid startup cost
        self._iam_token = None
        self._iam_expiry = 0

    def _get_iam_token(self) -> str:
        if self._iam_token and time.time() < self._iam_expiry - 60:
            return self._iam_token
        try:
            response = requests.post(
                "https://iam.cloud.ibm.com/identity/token",
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": WATSONX_API_KEY,
                },
                timeout=15,
            )
            payload = response.json()
            self._iam_token = payload.get("access_token", "")
            self._iam_expiry = time.time() + payload.get("expires_in", 3600)
            return self._iam_token
        except Exception:
            return ""

    def _granite_guardian_check(self, text: str, stage: str) -> tuple[bool, dict[str, object]]:
        token = self._get_iam_token()
        if not token:
            raise RuntimeError("Granite Guardian unavailable: IAM token failed")

        prompt = (
            "You are a safety classifier. Return ONLY compact JSON with keys: "
            "decision (ALLOW or BLOCK), risk_score (0..1), categories (array of strings), reason (short). "
            f"Assess this {stage} text for safety policy risks (violence, self-harm, hate, sexual violence, doxxing):\n"
            f"{text[:2500]}"
        )
        payload = {
            "model_id": GRANITE_GUARDIAN_MODEL,
            "project_id": WATSONX_PROJECT_ID,
            "input": prompt,
            "parameters": {
                "decoding_method": "greedy",
                "max_new_tokens": 180,
                "repetition_penalty": 1.0,
            },
        }
        response = requests.post(
            f"{WATSONX_URL}/ml/v1/text/generation?version=2023-05-29",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        generated = response.json().get("results", [{}])[0].get("generated_text", "").strip()
        cleaned = generated.replace("```json", "").replace("```", "").strip()

        data = None
        # 1) Try full cleaned payload as JSON.
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = None

        # 2) Try first JSON object substring.
        if data is None:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, dict):
                        data = parsed
                except Exception:
                    data = None

        # 3) Try line-by-line JSON parse fallback.
        if data is None:
            for line in cleaned.splitlines():
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        data = parsed
                        break
                except Exception:
                    continue

        source = "granite_guardian"
        if data is None:
            # 4) Free-text classifier fallback for Granite Guardian responses that
            # are not strict JSON but still contain a clear safety verdict.
            lowered = cleaned.lower()
            decision = "ALLOW"
            if any(tok in lowered for tok in ["block", "unsafe", "disallow", "not allowed", "high risk"]):
                decision = "BLOCK"

            risk_score = 0.0
            score_match = re.search(r"(risk|score|confidence)\s*[:=]\s*([0-9]*\.?[0-9]+)", lowered)
            if score_match:
                try:
                    risk_score = float(score_match.group(2))
                    # Convert percentage-style score to 0..1 if needed.
                    if risk_score > 1.0:
                        risk_score = risk_score / 100.0
                except Exception:
                    risk_score = 0.0
            elif decision == "BLOCK":
                risk_score = 0.8

            category_terms = {
                "violence": ["violence", "violent", "weapon", "bomb", "attack"],
                "self_harm": ["self-harm", "self harm", "suicide", "kill myself"],
                "hate": ["hate", "slur", "racist", "nazi"],
                "sexual": ["sexual", "rape", "assault"],
                "doxxing": ["dox", "address", "phone number", "personal info"],
            }
            categories = [
                category
                for category, terms in category_terms.items()
                if any(term in lowered for term in terms)
            ]
            reason = cleaned[:240] if cleaned else "Granite Guardian free-text response"
            source = "granite_guardian_text"
        else:
            decision = str(data.get("decision", "ALLOW")).upper()
            risk_score = float(data.get("risk_score", 0.0))
            categories = data.get("categories") if isinstance(data.get("categories"), list) else []
            reason = str(data.get("reason", "Granite Guardian check complete"))

        blocked = decision == "BLOCK" or risk_score >= GRANITE_GUARDIAN_THRESHOLD

        return (not blocked), {
            "configured": True,
            "passed": not blocked,
            "source": source,
            "model": GRANITE_GUARDIAN_MODEL,
            "decision": decision,
            "risk_score": round(risk_score, 3),
            "threshold": GRANITE_GUARDIAN_THRESHOLD,
            "categories": categories,
            "reason": reason,
        }

    def _moderation_check(self, text: str, stage: str) -> tuple[bool, dict[str, object]]:
        """
        Deterministic moderation guardrail.
        Returns (passed, details) without external dependencies.
        """
        if not text:
            return True, {
                "configured": True,
                "passed": True,
                "reason": "No text to moderate",
                "source": "granite_guardian" if USE_GRANITE_GUARDIAN else "heuristic",
            }

        heuristic_patterns = [
            r"\b(kill myself|suicid|self[- ]harm)\b",
            r"\b(hate|slur|racist|nazi|exterminate)\b",
            r"\b(rape|sexual assault|explicit sex)\b",
            r"\b(behead|massacre|terrorist|bomb|shoot up)\b",
            r"\b(doxx|address is|phone number is)\b",
        ]
        lowered = text.lower()
        heuristic_hit = any(re.search(pattern, lowered) for pattern in heuristic_patterns)

        guardian_error = None
        # Granite Guardian is calibrated for user-generated content (input/retrieval).
        # Applying it to LLM output (stage="output") causes false positives on legitimate
        # emergency management language (HAZMAT, INFRASTRUCTURE RISK, gas leak, etc.).
        # Heuristic-only moderation is sufficient for controlled pipeline output.
        if USE_GRANITE_GUARDIAN and stage != "output":
            try:
                guardian_passed, guardian_details = self._granite_guardian_check(text, stage)
                # Conservative union rule: block if either detector flags.
                if heuristic_hit:
                    guardian_details["passed"] = False
                    guardian_details["source"] = f"{guardian_details.get('source', 'granite_guardian')}+heuristic"
                    guardian_details["reason"] = f"Heuristic moderation flagged {stage} text"
                    guardian_details["heuristic_override"] = True
                    return False, guardian_details
                return guardian_passed, guardian_details
            except Exception as exc:
                guardian_error = str(exc)

        if heuristic_hit:
            return False, {
                "configured": not USE_GRANITE_GUARDIAN or guardian_error is None,
                "passed": False,
                "source": "heuristic",
                "reason": f"Heuristic moderation flagged {stage} text",
                "guardian_error": guardian_error,
            }

        return True, {
            "configured": not USE_GRANITE_GUARDIAN or guardian_error is None,
            "passed": True,
            "source": "heuristic",
            "reason": f"No moderation issues detected for {stage}",
            "guardian_error": guardian_error,
        }

    # ── HOOK 1: Input Audit ───────────────────────────────────
    def input_audit(self, intent: dict) -> bool:
        """
        Earliest possible intervention.
        Catches structuring failures before reasoning begins.
        """
        passed = intent.get("is_complete", False)
        reason = "Intent complete" if passed else "Location or crisis type missing"
        if passed:
            moderated, moderation = self._moderation_check(intent.get("raw_input", ""), "input")
            intent["moderation"] = moderation
            passed = passed and moderated
            if not moderated:
                reason = moderation.get("reason", "Moderation failed")
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
        if passed:
            moderated, moderation = self._moderation_check(retrieval.get("context", ""), "retrieval")
            retrieval["moderation"] = moderation
            passed = passed and moderated
            if not moderated:
                reason = moderation.get("reason", reason)
        self.log.record("retrieval_audit", {"confidence": confidence}, passed, reason)
        return passed

    # ── HOOK 3: Pre-Delivery Check ────────────────────────────
    def pre_delivery_check(self, output: str, citation: str, context: str = "") -> tuple:
        """
        Cross-validates the generated output against its cited source.
        The last gate before the citizen receives anything.

        Returns (passed: bool, citation_score: float).

        Three sequential checks:
        1. Unfilled template detection — catches prompt artifacts
           that expose scaffolding to the emergency manager.
        1.5. Required section structure — verifies all three headers
           ([HAZARD STATUS], [DEMOGRAPHIC RISK (SVI)], [INTER-AGENCY ROUTING])
           are present. Format drift is invisible to citation alignment.
        2. Citation alignment scoring — catches source mismatches.

        All must pass. A structurally complete output that scores 1.00
        on citation alignment still fails Check 1 if it contains an
        unfilled template signal.
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

        # ── Check 0: Moderation guardrail ─────────────────────
        moderated, moderation = self._moderation_check(output, "output")
        if not moderated:
            self.log.record(
                "pre_delivery_check",
                {"citation": citation, "moderation": moderation},
                False,
                moderation.get("reason", "Moderation failed")
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

        # ── Check 1.5: Required section structure ─────────────
        sections_ok, missing_sections = self._has_required_sections(output)
        if not sections_ok:
            self.log.record(
                "pre_delivery_check",
                {"citation": citation, "missing_sections": missing_sections},
                False,
                f"Output missing required sections: {missing_sections}"
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

    def _has_required_sections(self, output: str) -> tuple[bool, list[str]]:
        """
        Verifies all three mandatory section headers are present.
        Enforces the structural contract defined by SynthesisAgent._normalize_section_headers().
        Returns (all_present, missing_sections).
        """
        missing = [s for s in REQUIRED_SECTIONS if s not in output]
        return len(missing) == 0, missing

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
