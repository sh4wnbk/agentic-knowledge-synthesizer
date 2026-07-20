"""
providers/anthropic.py
Anthropic Messages API.

Uses requests rather than the anthropic SDK so the repo adds no new
dependency and the test suite still runs from a bare clone.
"""

import requests

from providers.base import LLMProvider


class AnthropicProvider(LLMProvider):

    name = "anthropic"

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key=None, model=None):
        from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.model   = model   or ANTHROPIC_MODEL

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)

    def generate(self, prompt: str, temperature: float, max_tokens: int) -> str:
        try:
            r = requests.post(
                self.API_URL,
                headers={
                    "x-api-key":         self.api_key,
                    "anthropic-version": self.API_VERSION,
                    "Content-Type":      "application/json",
                },
                json={
                    "model":       self.model,
                    "max_tokens":  max_tokens,
                    "temperature": temperature,
                    "messages":    [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            result = r.json()
            if "error" in result:
                print(f"[PROVIDER:anthropic] API error: {result['error']}")
                return ""
            return "".join(
                block.get("text", "")
                for block in result.get("content", [])
                if block.get("type") == "text"
            )
        except Exception as e:
            print(f"[PROVIDER:anthropic] generation failed: {e}")
            return ""
