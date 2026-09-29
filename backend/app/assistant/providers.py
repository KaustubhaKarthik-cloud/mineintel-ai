"""LLM provider abstraction for assistant + topic summarization.

Supports mock, OpenAI-compatible remote APIs, and local Qwen via Ollama
(no API key required).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import httpx

from app.config import get_settings


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    def available(self) -> bool:
        return True


class MockLLMProvider(LLMProvider):
    """Template-based answers from supplied evidence only — no inventing numbers."""

    name = "mock"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return user_prompt


class OpenAILLMProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        settings = get_settings()
        self._key = settings.llm_api_key
        self._base = settings.llm_api_base.rstrip("/")
        self._model = settings.llm_model
        if not self._key:
            raise LLMError("LLM API key is not configured.")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self._base}/chat/completions"
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "temperature": 0.0,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
        except httpx.TimeoutException as exc:
            raise LLMError("LLM provider timed out.") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError("LLM provider request failed.") from exc


class LocalQwenProvider(LLMProvider):
    """Local Qwen-family instruct model via Ollama (OpenAI-compatible or native).

    No API key required. Safe fallback: callers should catch LLMError and use mock.
    Designed for RTX 3050 6GB — default model qwen2.5:1.5b-instruct.
    LoRA adapters can be layered later without changing this interface.
    """

    name = "local_qwen"

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        settings = get_settings()
        self._base = (base_url or settings.local_llm_base_url).rstrip("/")
        self._model = model or settings.local_llm_model
        self._timeout = timeout if timeout is not None else settings.local_llm_timeout_seconds

    def available(self) -> bool:
        try:
            with httpx.Client(timeout=3.0) as client:
                # Ollama native tags endpoint (no auth)
                r = client.get(f"{self._base}/api/tags")
                if r.status_code == 200:
                    return True
                # OpenAI-compatible probe
                r2 = client.get(f"{self._base}/v1/models")
                return r2.status_code < 500
        except Exception:  # noqa: BLE001
            return False

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        # Prefer OpenAI-compatible /v1/chat/completions (Ollama supports this)
        openai_url = f"{self._base}/v1/chat/completions"
        native_url = f"{self._base}/api/chat"
        headers = {"Content-Type": "application/json"}
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    openai_url,
                    headers=headers,
                    json={
                        "model": self._model,
                        "temperature": 0.0,
                        "messages": messages,
                        "stream": False,
                    },
                )
                if resp.status_code == 404:
                    # Native Ollama chat API
                    resp = client.post(
                        native_url,
                        headers=headers,
                        json={
                            "model": self._model,
                            "messages": messages,
                            "stream": False,
                            "options": {"temperature": 0.0},
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    msg = data.get("message") or {}
                    content = msg.get("content") or data.get("response") or ""
                    return str(content).strip()
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
        except httpx.TimeoutException as exc:
            raise LLMError("Local Qwen timed out.") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(
                f"Local Qwen unavailable ({self._model} @ {self._base}). "
                "Install Ollama and pull the model, or set ASSISTANT_LLM_PROVIDER=mock."
            ) from exc


def probe_local_llm() -> dict:
    """Status helper for settings/health — never raises."""
    settings = get_settings()
    if not settings.local_llm_enabled:
        return {"enabled": False, "available": False, "model": settings.local_llm_model}
    provider = LocalQwenProvider()
    ok = provider.available()
    return {
        "enabled": True,
        "available": ok,
        "model": settings.local_llm_model,
        "base_url": settings.local_llm_base_url,
        "provider": "local_qwen",
    }


def get_assistant_llm() -> LLMProvider:
    """Factory: mock by default; local Qwen when configured and reachable; OpenAI if keyed."""
    settings = get_settings()
    provider = (settings.assistant_llm_provider or settings.llm_provider or "mock").lower().strip()

    if provider in {"local_qwen", "ollama", "qwen"}:
        if not settings.local_llm_enabled:
            return MockLLMProvider()
        local = LocalQwenProvider()
        if local.available():
            return local
        return MockLLMProvider()

    if provider in {"openai", "compatible"} and settings.llm_api_key:
        return OpenAILLMProvider()

    # Optional auto-prefer local when mock requested but local is up and explicitly enabled
    # Keep default mock to preserve deterministic tests unless provider asks for local.
    return MockLLMProvider()
