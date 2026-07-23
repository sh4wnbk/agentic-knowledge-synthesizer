"""
providers/openai_compat.py
Any endpoint that speaks the OpenAI /chat/completions schema.

That covers OpenAI, Groq, Together, OpenRouter, vLLM, Ollama (/v1), and
LM Studio. Point LLM_BASE_URL at the host and set LLM_MODEL. Local hosts
such as Ollama accept any non-empty API key.

Uses requests rather than the openai SDK so the repo adds no new dependency
and the test suite still runs from a bare clone.
"""

import time

import requests

from providers.base import LLMProvider, is_real_credential


class OpenAICompatProvider(LLMProvider):

    name = "openai"

    # Transient statuses worth retrying: rate limit + gateway/5xx. A throttled
    # beam should back off and retry rather than drop, which on a rate-limited
    # key would otherwise fail every beam and trip SynthesisUnavailable.
    _RETRYABLE = {429, 500, 502, 503, 504}
    _MAX_ATTEMPTS = 3

    def __init__(self, api_key=None, base_url=None, model=None):
        from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
        self.api_key  = api_key  or LLM_API_KEY
        self.base_url = (base_url or LLM_BASE_URL).rstrip("/")
        self.model    = model    or LLM_MODEL

    def is_configured(self) -> bool:
        return is_real_credential(self.api_key) and bool(self.base_url and self.model)

    def generate(self, prompt: str, temperature: float, max_tokens: int) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        body = {
            "model":       self.model,
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }

        r = None
        for attempt in range(self._MAX_ATTEMPTS):
            try:
                r = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers, json=body, timeout=90,
                )
            except Exception as e:
                print(f"[PROVIDER:openai] request failed: {type(e).__name__}: {e}")
                return ""

            if r.status_code == 200:
                break

            if r.status_code in self._RETRYABLE and attempt < self._MAX_ATTEMPTS - 1:
                # Respect Retry-After when the server sends it, else exponential
                # backoff (2s, 4s), capped so a slow beam does not stall delivery.
                retry_after = r.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else 2.0 * (2 ** attempt)
                except ValueError:
                    wait = 2.0 * (2 ** attempt)
                wait = min(wait, 8.0)
                print(f"[PROVIDER:openai] HTTP {r.status_code}, retrying in {wait:.1f}s "
                      f"(attempt {attempt + 1}/{self._MAX_ATTEMPTS})")
                time.sleep(wait)
                continue

            # Non-retryable, or retries exhausted: surface the real status/body
            # instead of letting it collapse into a bare KeyError downstream.
            print(f"[PROVIDER:openai] HTTP {r.status_code}: {r.text[:500]}")
            return ""

        try:
            result = r.json()
        except ValueError:
            print(f"[PROVIDER:openai] non-JSON response: {r.text[:300]}")
            return ""
        if isinstance(result, dict) and result.get("error"):
            print(f"[PROVIDER:openai] API error: {result['error']}")
            return ""

        try:
            choice = result["choices"][0]
        except (KeyError, IndexError, TypeError):
            print(f"[PROVIDER:openai] unexpected response shape: {str(result)[:400]}")
            return ""

        content = (choice.get("message") or {}).get("content")
        if content:
            return content

        # Empty content with tokens spent usually means a reasoning model hit the
        # token ceiling during hidden reasoning (finish_reason=length) before it
        # produced any answer. Report it so it does not masquerade as a refusal.
        print(
            f"[PROVIDER:openai] empty content "
            f"(finish_reason={choice.get('finish_reason')}, usage={result.get('usage')}). "
            f"If finish_reason=length on a reasoning model, raise MAX_NEW_TOKENS."
        )
        return ""
