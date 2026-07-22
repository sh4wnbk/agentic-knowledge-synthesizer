"""
providers/base.py
The LLM provider contract.

AEGIS does not care which model writes the candidate brief. It cares that
BEAM_WIDTH meaningfully different candidates come back as plain text, so the
Overseer can score them for citation alignment. That is the whole interface.

Everything AEGIS-specific (prompt construction, header normalization, beam
scheduling, Overseer scoring) lives in agents/synthesis_agent.py, not here.
"""

import re
from abc import ABC, abstractmethod


class ProviderNotConfigured(RuntimeError):
    """Raised when a provider is selected but its credentials are missing."""
    pass


# Obvious dummy values from .env.example (e.g. "your_api_key_here",
# "your_ibm_cloud_api_key_here"). A non-empty check alone treats these as
# configured, which lets auto-detect select a provider that cannot authenticate.
_PLACEHOLDER_RE = re.compile(
    r"^(your[_-].*|.*_here|changeme|placeholder|todo|x{3,}|<.*>)$",
    re.IGNORECASE,
)


def is_real_credential(value) -> bool:
    """True when value is a non-empty string that is not an obvious placeholder."""
    if not isinstance(value, str):
        return False
    v = value.strip()
    return bool(v) and _PLACEHOLDER_RE.match(v) is None


class LLMProvider(ABC):
    """
    Minimal text-in, text-out contract.

    Implementations must not raise on a failed call. A failed generation
    returns an empty string, which the Synthesis Agent treats as a dropped
    beam. If every beam drops, the pipeline reaches Honest Fallback rather
    than delivering an unvalidated brief.
    """

    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """True when the credentials this provider needs are present."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt: str, temperature: float, max_tokens: int) -> str:
        """Return generated text, or an empty string on failure."""
        raise NotImplementedError

    def describe(self) -> dict:
        """Provenance record for the audit log."""
        return {"provider": self.name, "model": getattr(self, "model", None)}
