"""Google Gemini LLM Provider implementation for AO-03.
"""

import json
import logging
import requests
from app.config import Config
from app.llm.provider import BaseLLMProvider

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or Config.GEMINI_API_KEY
        self.model = model or Config.GEMINI_MODEL or "gemini-1.5-flash"
        self.endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        )

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if not self.is_available():
            raise RuntimeError("Gemini API key is not configured.")

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": f"{system_prompt}\n\nUser Request:\n{user_prompt}"}
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        response = requests.post(
            self.endpoint,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )

        if response.status_code != 200:
            raise RuntimeError(f"Gemini API returned {response.status_code}: {response.text}")

        res_data = response.json()
        try:
            return res_data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Gemini response structure: {e}")
