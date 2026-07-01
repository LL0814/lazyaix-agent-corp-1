"""Model module.

A minimal OpenAI-compatible LLM client using only the Python standard library.
Reads endpoint credentials from environment variables and falls back to a
stub echo when nothing is configured, so the scaffold always runs.
"""

import json
import os
from urllib import error, request


class Model:
    """Minimal OpenAI-compatible LLM client using only stdlib urllib."""

    def __init__(self):
        self.api_key = os.environ.get("MODEL_API_KEY", "stub-key")
        self.base_url = os.environ.get("MODEL_BASE_URL", "").rstrip("/")
        self.model_name = os.environ.get("MODEL_NAME", "stub-llm")

    def complete(self, prompt: str) -> str:
        """Call the LLM and return raw text output.

        Falls back to a stub echo when no real endpoint is configured.
        """
        if not self.base_url or self.api_key == "stub-key":
            return f"[{self.model_name}] {prompt}"

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
        }

        req = request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except error.HTTPError as exc:
            return (
                f"[Model HTTP {exc.code}] "
                f"{exc.read().decode('utf-8', errors='replace')}"
            )
        except Exception as exc:  # pragma: no cover - defensive
            return f"[Model Error] {exc}"
