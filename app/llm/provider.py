"""Base LLM Provider abstraction for AO-03.
Ensures provider independence (Ollama, local mock, or other providers).
"""

from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Sends prompt to the LLM and returns the text response."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the provider is configured and reachable."""
        pass
