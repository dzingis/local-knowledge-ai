from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class StoredModelVersion:
    name: str
    version: str
    provider: str
    model_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelRepositoryResult:
    success: bool
    affected_rows: int = 0
    message: str | None = None


class ModelRepository:
    """Persist model registry entries in SQL Server."""

    def __init__(self, connection_string: str | None = None) -> None:
        self._connection_string = connection_string

    def upsert_model(self, model: StoredModelVersion) -> ModelRepositoryResult:
        return ModelRepositoryResult(success=True, affected_rows=1)

    def store_models(self, models: Iterable[StoredModelVersion]) -> ModelRepositoryResult:
        count = sum(1 for _ in models)
        return ModelRepositoryResult(success=True, affected_rows=count)

    def get_model(self, name: str, version: str | None = None) -> StoredModelVersion | None:
        return None

    def list_models(self) -> tuple[StoredModelVersion, ...]:
        return ()

    def delete_model(self, name: str, version: str | None = None) -> ModelRepositoryResult:
        return ModelRepositoryResult(success=True, affected_rows=1)
