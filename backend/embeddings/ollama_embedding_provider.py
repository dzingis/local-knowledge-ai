from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests

from backend.embeddings.embedding_models import EmbeddingProvider


class EmbeddingProviderClient(Protocol):
    def embed(self, text: str, model_name: str) -> tuple[float, ...]:
        ...


@dataclass(frozen=True, slots=True)
class OllamaEmbeddingProvider:
    base_url: str
    timeout_seconds: int = 30

    @property
    def provider(self) -> EmbeddingProvider:
        return EmbeddingProvider.OLLAMA

    def embed(self, text: str, model_name: str) -> tuple[float, ...]:
        payload = {"model": model_name, "prompt": text}
        response = requests.post(
            f"{self.base_url.rstrip('/')}/api/embeddings",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        embedding = data.get("embedding", [])
        return tuple(float(value) for value in embedding)
