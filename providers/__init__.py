"""
providers/
Model access for the Synthesis Agent.

Selection order:
  1. The name passed to get_provider()
  2. LLM_PROVIDER in the environment
  3. Auto-detect: the first registered provider whose credentials are present

If nothing is configured, ProviderNotConfigured is raised with the list of
options. The pipeline fails loudly at startup rather than silently producing
zero candidates and reporting Honest Fallback for a credentials problem.
"""

from providers.base import LLMProvider, ProviderNotConfigured

# Import order is the auto-detect priority order.
_REGISTRY = {}


def _load_registry():
    if _REGISTRY:
        return _REGISTRY
    from providers.anthropic import AnthropicProvider
    from providers.openai_compat import OpenAICompatProvider
    from providers.watsonx import WatsonxProvider
    _REGISTRY.update({
        "anthropic": AnthropicProvider,
        "openai":    OpenAICompatProvider,
        "watsonx":   WatsonxProvider,
    })
    return _REGISTRY


def available_providers() -> list:
    return list(_load_registry().keys())


def get_provider(name: str = None) -> LLMProvider:
    """
    Return a configured LLMProvider.

    Raises ProviderNotConfigured if the named provider is missing credentials,
    or if auto-detect finds none configured.
    """
    registry = _load_registry()

    if name is None:
        from config import LLM_PROVIDER
        name = LLM_PROVIDER

    if name:
        name = name.strip().lower()
        if name not in registry:
            raise ProviderNotConfigured(
                f"Unknown provider '{name}'. Available: {', '.join(registry)}"
            )
        provider = registry[name]()
        if not provider.is_configured():
            raise ProviderNotConfigured(
                f"Provider '{name}' is selected but its credentials are not set. "
                f"See .env.example."
            )
        return provider

    for candidate_name, candidate_cls in registry.items():
        candidate = candidate_cls()
        if candidate.is_configured():
            print(f"[PROVIDER] Auto-detected '{candidate_name}'.")
            return candidate

    raise ProviderNotConfigured(
        "No LLM provider configured. Set LLM_PROVIDER and the matching "
        f"credentials in .env. Available: {', '.join(registry)}"
    )


__all__ = [
    "LLMProvider",
    "ProviderNotConfigured",
    "get_provider",
    "available_providers",
]
