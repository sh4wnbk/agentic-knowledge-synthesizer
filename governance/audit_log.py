"""
governance/audit_log.py
Every Overseer decision is recorded here.
In production: writes to IBM watsonx.governance API.
In prototype: writes to local JSON log and stdout.
"""

import json
import datetime


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
        """Truncate large payloads for log readability."""
        truncated = {}
        for k, v in data.items():
            s = str(v)
            truncated[k] = s[:200] + "..." if len(s) > 200 else s
        return truncated

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
