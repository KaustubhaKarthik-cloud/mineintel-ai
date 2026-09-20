"""Embedding provider abstraction (Phase 4)."""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

import httpx
import numpy as np

from app.config import get_settings


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(ABC):
    name: str = "base"
    dimensions: int = 384

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic hashed bag-of-ngrams embeddings — offline, no paid API.

    Overlapping mining terminology yields higher cosine similarity.
    """

    name = "mock"

    def __init__(self, dimensions: int | None = None) -> None:
        settings = get_settings()
        # Keep mock dims modest for SQLite JSON storage
        self.dimensions = dimensions or min(384, settings.embedding_dimensions or 384)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    @staticmethod
    def _light_stem(token: str) -> str:
        for suf in ("tions", "tion", "ings", "ing", "ied", "ies", "ed", "es", "s"):
            if len(token) > len(suf) + 2 and token.endswith(suf):
                return token[: -len(suf)]
        return token

    def _embed_one(self, text: str) -> list[float]:
        vec = np.zeros(self.dimensions, dtype=np.float64)
        lowered = (text or "").lower()
        tokens = re.findall(r"[a-z0-9\.]+", lowered)
        if not tokens:
            tokens = ["empty"]
        stems = [self._light_stem(t) for t in tokens]
        # stems + bigrams + character n-grams (helps produced≈production)
        grams: list[str] = list(stems)
        grams.extend(f"{a}_{b}" for a, b in zip(stems, stems[1:]))
        compact = re.sub(r"[^a-z0-9]", "", lowered)
        for n in (3, 4):
            grams.extend(compact[i : i + n] for i in range(max(0, len(compact) - n + 1)))
        for g in grams:
            h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimensions
            sign = 1.0 if (h // self.dimensions) % 2 == 0 else -1.0
            weight = 1.0 + math.log1p(len(g))
            vec[idx] += sign * weight
        norm = np.linalg.norm(vec)
        if norm == 0:
            vec[0] = 1.0
            norm = 1.0
        vec = vec / norm
        return vec.astype(float).tolist()


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(self) -> None:
        settings = get_settings()
        self.dimensions = settings.embedding_dimensions
        self._model = settings.embedding_model
        self._base = settings.embedding_api_base.rstrip("/")
        self._key = settings.embedding_api_key
        if not self._key:
            raise EmbeddingError("Embedding API key is not configured.")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self._base}/embeddings"
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self._model, "input": texts},
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                data = sorted(data, key=lambda x: x["index"])
                return [row["embedding"] for row in data]
        except httpx.TimeoutException as exc:
            raise EmbeddingError("Embedding provider timed out.") from exc
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError("Embedding provider request failed.") from exc


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    provider = (settings.embedding_provider or "mock").lower().strip()
    if provider in {"openai", "compatible"} and settings.embedding_api_key:
        return OpenAIEmbeddingProvider()
    return MockEmbeddingProvider()
