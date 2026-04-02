"""
governance/output_states.py
OutputState enum and AgentOutput dataclass.
Three states only. No fourth state is permitted.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OutputState(Enum):
    CONFIRMED_DELIVERY       = "confirmed_delivery"
    RETRY_CORRECTED_DELIVERY = "retry_corrected_delivery"
    HONEST_FALLBACK          = "honest_fallback"


@dataclass
class AgentOutput:
    state:            OutputState
    content:          str
    citation:         Optional[str]
    confidence:       float
    citation_score:   float
    audit_log:        list = field(default_factory=list)

    def display(self):
        print(f"\n{'─'*50}")
        print(f"  OUTPUT STATE:    {self.state.value}")
        print(f"  CONFIDENCE:      {self.confidence:.2f}")
        print(f"  CITATION SCORE:  {self.citation_score:.2f}")
        print(f"  CITATION:        {self.citation}")
        print(f"\n  CONTENT:\n  {self.content}")
        print(f"\n  AUDIT LOG:")
        for entry in self.audit_log:
            status = "PASS" if entry["passed"] else "FAIL"
            print(f"    [{entry['hook']}] → {status}")
        print(f"{'─'*50}\n")
