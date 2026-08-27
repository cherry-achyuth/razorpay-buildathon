"""Embedding provider abstractions and implementations for DecisionVault."""

import hashlib
import logging
import math
import random
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract interface for generating vector embeddings."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name/identifier of the embedding model."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of output embedding vectors."""
        pass

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate a normalized vector embedding for a single text."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate normalized vector embeddings for multiple texts."""
        pass


class DeterministicHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic, hermetic embedding provider for local development and testing.

    Generates reproducible unit-norm float vectors using cryptographic hashing
    and seeded pseudo-random projections. Requires zero external network calls.
    """

    def __init__(
        self,
        dimension: int = 384,
        model_name: str = "deterministic-hash-v1",
    ) -> None:
        self._dimension = dimension
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _generate_vector(self, text: str) -> list[float]:
        """Generates a deterministic unit-norm vector from input text."""
        if not text or not text.strip():
            return [0.0] * self._dimension

        # Seed PRNG with SHA-256 digest of normalized text
        norm_text = text.strip().lower()
        seed_bytes = hashlib.sha256(norm_text.encode("utf-8")).digest()
        seed_int = int.from_bytes(seed_bytes[:8], byteorder="big")

        rng = random.Random(seed_int)
        raw_vector = [rng.gauss(0.0, 1.0) for _ in range(self._dimension)]

        # L2-normalize
        norm = math.sqrt(sum(x * x for x in raw_vector))
        if norm == 0.0:
            return [0.0] * self._dimension
        return [float(x / norm) for x in raw_vector]

    async def embed(self, text: str) -> list[float]:
        """Generate deterministic embedding vector."""
        return self._generate_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate deterministic embedding vectors for batch."""
        return [self._generate_vector(t) for t in texts]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI API embedding provider using text-embedding-3-small."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "text-embedding-3-small",
        dimension: int = 384,
    ) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        import httpx

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "input": text,
            "model": self._model_name,
            "dimensions": self._dimension,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        import httpx

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "input": texts,
            "model": self._model_name,
            "dimensions": self._dimension,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]


def get_embedding_provider() -> EmbeddingProvider:
    """Factory function returning configured embedding provider."""
    settings = get_settings()
    provider_type = getattr(settings, "EMBEDDING_PROVIDER", "deterministic").lower()

    if provider_type == "openai" and getattr(settings, "OPENAI_API_KEY", None):
        return OpenAIEmbeddingProvider(
            api_key=settings.OPENAI_API_KEY,  # type: ignore[arg-type]
            model_name=getattr(settings, "EMBEDDING_MODEL", "text-embedding-3-small"),
            dimension=getattr(settings, "EMBEDDING_DIMENSION", 384),
        )

    return DeterministicHashEmbeddingProvider(
        dimension=getattr(settings, "EMBEDDING_DIMENSION", 384),
        model_name=getattr(settings, "EMBEDDING_MODEL", "deterministic-hash-v1"),
    )
