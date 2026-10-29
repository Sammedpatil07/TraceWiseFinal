"""Unit tests for the Ollama LLM Provider.
All tests mock HTTP responses — no running Ollama instance required.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
import requests

from app.llm.ollama_provider import OllamaProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_tags_response(models=None):
    """Return a mock /api/tags response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "models": [{"name": m} for m in (models or ["qwen2.5:0.5b"])]
    }
    return resp


def _mock_chat_response(content: str, status_code: int = 200, as_json: bool = True):
    """Return a mock /api/chat response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = content if not as_json else json.dumps({"message": {"role": "assistant", "content": content}})
    if as_json:
        resp.json.return_value = {"message": {"role": "assistant", "content": content}}
    else:
        resp.json.side_effect = ValueError("Not JSON")
    return resp


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestOllamaIsAvailable:
    @patch("app.llm.ollama_provider.requests.get")
    def test_available_when_model_exists(self, mock_get):
        mock_get.return_value = _mock_tags_response(["qwen2.5:0.5b"])
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        assert provider.is_available() is True

    @patch("app.llm.ollama_provider.requests.get")
    def test_unavailable_when_model_missing(self, mock_get):
        mock_get.return_value = _mock_tags_response(["llama3:latest"])
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        assert provider.is_available() is False

    @patch("app.llm.ollama_provider.requests.get")
    def test_unavailable_on_connection_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("refused")
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        assert provider.is_available() is False

    @patch("app.llm.ollama_provider.requests.get")
    def test_unavailable_on_http_error(self, mock_get):
        resp = MagicMock()
        resp.status_code = 500
        mock_get.return_value = resp
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        assert provider.is_available() is False


# ---------------------------------------------------------------------------
# generate — successful
# ---------------------------------------------------------------------------

class TestOllamaGenerate:
    @patch("app.llm.ollama_provider.requests.post")
    def test_successful_generation(self, mock_post):
        expected = json.dumps({"header": "AI-GENERATED", "summary": "test"})
        mock_post.return_value = _mock_chat_response(expected)
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        result = provider.generate("system", "user")
        assert result == expected

    @patch("app.llm.ollama_provider.requests.post")
    def test_plain_text_response(self, mock_post):
        mock_post.return_value = _mock_chat_response("Hello world")
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        result = provider.generate("system", "user")
        assert result == "Hello world"


# ---------------------------------------------------------------------------
# generate — error handling
# ---------------------------------------------------------------------------

class TestOllamaErrors:
    @patch("app.llm.ollama_provider.requests.post")
    def test_connection_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("refused")
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        with pytest.raises(RuntimeError, match="Cannot connect to Ollama"):
            provider.generate("sys", "usr")

    @patch("app.llm.ollama_provider.requests.post")
    def test_timeout_error(self, mock_post):
        mock_post.side_effect = requests.Timeout("timed out")
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        with pytest.raises(RuntimeError, match="timed out"):
            provider.generate("sys", "usr")

    @patch("app.llm.ollama_provider.requests.post")
    def test_model_not_found_404(self, mock_post):
        resp = MagicMock()
        resp.status_code = 404
        mock_post.return_value = resp
        provider = OllamaProvider(base_url="http://localhost:11434", model="nonexistent:latest")
        with pytest.raises(RuntimeError, match="not found on Ollama"):
            provider.generate("sys", "usr")

    @patch("app.llm.ollama_provider.requests.post")
    def test_server_error_500(self, mock_post):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "internal server error"
        mock_post.return_value = resp
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        with pytest.raises(RuntimeError, match="HTTP 500"):
            provider.generate("sys", "usr")

    @patch("app.llm.ollama_provider.requests.post")
    def test_malformed_json_response(self, mock_post):
        mock_post.return_value = _mock_chat_response("not json at all", as_json=False)
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        with pytest.raises(RuntimeError, match="malformed response"):
            provider.generate("sys", "usr")

    @patch("app.llm.ollama_provider.requests.post")
    def test_unexpected_response_structure(self, mock_post):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"unexpected_key": "value"}
        mock_post.return_value = resp
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        with pytest.raises(RuntimeError, match="Unexpected Ollama response"):
            provider.generate("sys", "usr")

    @patch("app.llm.ollama_provider.requests.post")
    def test_empty_content_field(self, mock_post):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"message": {"role": "assistant", "content": ""}}
        mock_post.return_value = resp
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        result = provider.generate("sys", "usr")
        assert result == ""

    @patch("app.llm.ollama_provider.requests.post")
    def test_content_returned_as_is(self, mock_post):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"message": {"role": "assistant", "content": "```json\n{\"a\": 1}\n```"}}
        mock_post.return_value = resp
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:0.5b")
        result = provider.generate("sys", "usr")
        assert result == "```json\n{\"a\": 1}\n```"


