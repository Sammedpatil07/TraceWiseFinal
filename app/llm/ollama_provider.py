"""Local Ollama LLM Provider implementation for AO-03.
Uses the Ollama REST API for fully local inference — no API key required.
"""

import json
import logging
import requests
from app.config import Config
from app.llm.provider import BaseLLMProvider

logger = logging.getLogger(__name__)

# Sentinel used internally; never exposed to end-users.
_OLLAMA_CONNECT_ERROR = "OLLAMA_UNREACHABLE"


class OllamaProvider(BaseLLMProvider):
    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = (base_url or Config.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or Config.OLLAMA_MODEL or "qwen2.5:0.5b"
        self.chat_endpoint = f"{self.base_url}/api/chat"
        self.generate_endpoint = f"{self.base_url}/api/generate"
        self._timeout = 60  # seconds — local models can be slow on first load

    # ------------------------------------------------------------------
    # BaseLLMProvider interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Returns True if Ollama is reachable and the configured model exists."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            # Ollama lists models as "name:tag"; match with or without tag
            return any(
                self.model == m or self.model == m.split(":")[0]
                for m in models
            )
        except requests.ConnectionError:
            logger.warning(
                "Ollama is not reachable at %s. "
                "Please start Ollama and ensure the model '%s' is pulled.",
                self.base_url,
                self.model,
            )
            return False
        except Exception as exc:
            logger.warning("Ollama availability check failed: %s", exc)
            return False

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Sends a chat-completion request to the local Ollama instance.

        Uses ``/api/chat`` with system + user messages so that the model
        properly separates instruction context from the investigation data.
        Streaming is disabled (``"stream": false``) to receive the full
        response in a single JSON payload.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }

        try:
            response = requests.post(
                self.chat_endpoint,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self._timeout,
            )
        except requests.ConnectionError:
            raise RuntimeError(
                "Cannot connect to Ollama. Please ensure Ollama is running "
                f"at {self.base_url} and the model '{self.model}' is available. "
                "Start Ollama with: ollama serve"
            )
        except requests.Timeout:
            raise RuntimeError(
                f"Ollama request timed out after {self._timeout}s. "
                "The model may still be loading. Please try again."
            )

        if response.status_code == 404:
            raise RuntimeError(
                f"Model '{self.model}' not found on Ollama. "
                f"Pull it first with: ollama pull {self.model}"
            )

        if response.status_code != 200:
            # Do not leak raw Ollama internals to the caller — log them instead.
            logger.error(
                "Ollama returned HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )
            raise RuntimeError(
                f"Ollama returned an error (HTTP {response.status_code}). "
                "Check the application logs for details."
            )

        try:
            res_data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            logger.error("Ollama returned non-JSON response: %s", exc)
            raise RuntimeError(
                "Ollama returned a malformed response. "
                "Check the application logs for details."
            )

        # /api/chat returns {"message": {"role": "assistant", "content": "..."}}
        try:
            return res_data["message"]["content"]
        except (KeyError, TypeError) as exc:
            logger.error(
                "Unexpected Ollama response structure: %s — payload: %s",
                exc,
                json.dumps(res_data)[:500],
            )
            raise RuntimeError(
                "Unexpected Ollama response structure. "
                "Check the application logs for details."
            )
