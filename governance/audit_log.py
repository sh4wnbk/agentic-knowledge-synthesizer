"""
governance/audit_log.py
Every Overseer decision is recorded here.
In production: writes to IBM watsonx.governance API.
In prototype: writes to local JSON log and stdout.
"""

import json
import datetime
import ast


class AuditLog:

    def __init__(self):
        self.entries = []

    def record(self, hook: str, data: dict, passed: bool, reason: str = ""):
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "hook":      hook,
            "passed":    passed,
            "reason":    reason,
            "data":      self._safe_truncate(data)
        }
        self.entries.append(entry)
        self._print(entry)

    def _print(self, entry: dict):
        status = "PASS" if entry["passed"] else "FAIL"
        print(f"[OVERSEER | {entry['hook']}] → {status}"
              + (f" | {entry['reason']}" if entry["reason"] else ""))

    def _safe_truncate(self, data: dict) -> dict:
        """Truncate large payloads while preserving structured types."""
        truncated = {}
        for k, v in data.items():
            truncated[k] = self._normalize_value(v)
        return truncated

    def _normalize_value(self, value):
        """Keep dictionaries/lists structured; only truncate long leaf strings."""
        if isinstance(value, dict):
            return {k: self._normalize_value(v) for k, v in value.items()}

        if isinstance(value, list):
            return [self._normalize_value(v) for v in value]

        if isinstance(value, str):
            parsed = self._parse_structured_string(value)
            if parsed is not None:
                return self._normalize_value(parsed)
            return value[:200] + "..." if len(value) > 200 else value

        # Keep scalars as-is for machine-readability.
        return value

    def _parse_structured_string(self, text: str):
        """
        Parse JSON or Python-literal dict/list strings when present.
        This fixes moderation fields that may arrive as serialized strings.
        """
        candidate = text.strip()
        if not candidate or candidate[0] not in "[{":
            return None

        try:
            return json.loads(candidate)
        except Exception:
            pass

        try:
            parsed = ast.literal_eval(candidate)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            return None

        return None

    def export(self, path: str = "audit_log.json"):
        """
        Export full audit log to JSON.
        In production: POST to watsonx.governance endpoint.
        """
        with open(path, "w") as f:
            json.dump(self.entries, f, indent=2)
        print(f"[AUDIT LOG] Exported to {path}")

    def to_list(self) -> list:
        return self.entries
