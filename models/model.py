"""Real Model implementation using Kimi's OpenAI-compatible API."""

import os

from openai import OpenAI


class Model:
    """Loads config and exposes an LLM complete() method via Kimi API."""

    def __init__(self):
        self.api_key = os.environ.get("MODEL_API_KEY", "")
        self.model_name = os.environ.get("MODEL_NAME", "kimi-for-coding")
        self.base_url = os.environ.get("MODEL_URL", "https://api.kimi.com/coding/v1")
        self._client = None
        self.last_usage = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def complete(self, prompt: str) -> str:
        """Call the LLM and return raw text output."""
        if not self.api_key:
            raise RuntimeError(
                "MODEL_API_KEY is not set. Please copy .env.example to .env and fill in your API key."
            )

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )

        self.last_usage = response.usage
        return response.choices[0].message.content or ""
