"""
providers/watsonx.py
IBM watsonx.ai text generation, with IAM token caching.

This is the original AEGIS generation path, moved out of the Synthesis Agent
unchanged in behavior. It is now one option among several rather than the
only way the pipeline can run.
"""

import time
import requests

from providers.base import LLMProvider


class WatsonxProvider(LLMProvider):

    name = "watsonx"

    def __init__(self, api_key=None, project_id=None, url=None, model=None):
        from config import (
            WATSONX_API_KEY, WATSONX_PROJECT_ID, WATSONX_URL, GRANITE_MODEL
        )
        self.api_key    = api_key    or WATSONX_API_KEY
        self.project_id = project_id or WATSONX_PROJECT_ID
        self.url        = url        or WATSONX_URL
        self.model      = model      or GRANITE_MODEL
        self._token = None
        self._token_expiry = 0

    def is_configured(self) -> bool:
        return bool(self.api_key and self.project_id)

    def generate(self, prompt: str, temperature: float, max_tokens: int) -> str:
        token = self._get_iam_token()
        if not token:
            return ""
        payload = {
            "model_id":   self.model,
            "project_id": self.project_id,
            "input":      prompt,
            "parameters": {
                "decoding_method":    "sample",
                "temperature":        temperature,
                "max_new_tokens":     max_tokens,
                "repetition_penalty": 1.1,
            },
        }
        try:
            r = requests.post(
                f"{self.url}/ml/v1/text/generation?version=2023-05-29",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json",
                },
                json=payload,
                timeout=30,
            )
            result = r.json()
            return result.get("results", [{}])[0].get("generated_text", "")
        except Exception as e:
            print(f"[PROVIDER:watsonx] generation failed: {e}")
            return ""

    def _get_iam_token(self) -> str:
        # Refresh if missing or expiring within 60 seconds.
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        try:
            r = requests.post(
                "https://iam.cloud.ibm.com/identity/token",
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey":     self.api_key,
                },
                timeout=15,
            )
            payload = r.json()
            self._token = payload.get("access_token", "")
            self._token_expiry = time.time() + payload.get("expires_in", 3600)
            return self._token
        except Exception as e:
            print(f"[PROVIDER:watsonx] IAM token failed: {e}")
            return ""
