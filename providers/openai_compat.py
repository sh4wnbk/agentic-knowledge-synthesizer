"""
providers/openai_compat.py
Any endpoint that speaks the OpenAI /chat/completions schema.

That covers OpenAI, Groq, Together, OpenRouter, vLLM, Ollama (/v1), and
LM Studio. Point LLM_BASE_URL at the host and set LLM_MODEL. Local hosts
such as Ollama accept any non-empty API key.

Uses requests rather than the openai SDK so the repo adds no new dependency
and the test suite still runs from a bare clone.
"""

import requests

from providers.base import LLMProvider


class OpenAICompatProvider(LLMProvider):

    name = "openai"

    def __init__(self, api_key=None, base_url=None, model=None):
        from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
        self.api_key  = api_key  or LLM_API_KEY
        self.base_url = (base_url or LLM_BASE_URL).rstrip("/")
        self.model    = model    or LLM_MODEL

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def generate(self, prompt: str, temperature: float, max_tokens: int) -> str:
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       self.model,
                    "messages":    [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens":  max_tokens,
                },
                timeout=60,
            )
            result = r.json()
            if "error" in result:
                print(f"[PROVIDER:openai] API error: {result['error']}")
                return ""
            return result["choices"][0]["message"]["content"] or ""
        except Exception as e:
            print(f"[PROVIDER:openai] generation failed: {e}")
            return ""
