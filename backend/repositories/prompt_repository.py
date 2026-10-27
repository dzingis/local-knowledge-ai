from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import pyodbc

from backend.config.settings import get_settings


@dataclass(frozen=True, slots=True)
class StoredPromptVersion:
    prompt_name: str
    version: str
    prompt_text: str
    description: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class PromptRepositoryResult:
    prompt_name: str
    version: str
    stored: bool


class PromptRepository:
    """SQL-backed prompt storage for reusable system, retrieval, and agent prompts."""

    def __init__(self, connection_string: str | None = None) -> None:
        self._settings = get_settings()
        self._connection_string = connection_string or self._build_connection_string()

    def upsert_prompt(self, prompt: StoredPromptVersion) -> PromptRepositoryResult:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                MERGE AI.Prompts AS target
                USING (SELECT ? AS PromptName, ? AS Version) AS source
                ON target.PromptName = source.PromptName AND target.Version = source.Version
                WHEN MATCHED THEN
                    UPDATE SET
                        PromptText = ?,
                        Description = ?,
                        Tags = ?,
                        MetadataJson = ?,
                        CreatedAt = ?
                WHEN NOT MATCHED THEN
                    INSERT (
                        PromptName,
                        Version,
                        PromptText,
                        Description,
                        Tags,
                        MetadataJson,
                        CreatedAt
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    prompt.prompt_name,
                    prompt.version,
                    prompt.prompt_text,
                    prompt.description,
                    ",".join(prompt.tags),
                    self._to_json(prompt.metadata),
                    prompt.created_at,
                    prompt.prompt_name,
                    prompt.version,
                    prompt.prompt_text,
                    prompt.description,
                    ",".join(prompt.tags),
                    self._to_json(prompt.metadata),
                    prompt.created_at,
                ),
            )
            connection.commit()
            return PromptRepositoryResult(prompt_name=prompt.prompt_name, version=prompt.version, stored=True)

    def get_prompt(self, prompt_name: str, version: str | None = None) -> StoredPromptVersion | None:
        with self._connect() as connection:
            cursor = connection.cursor()
            if version is None:
                row = cursor.execute(
                    """
                    SELECT TOP 1 PromptName, Version, PromptText, Description, Tags, MetadataJson, CreatedAt
                    FROM AI.Prompts
                    WHERE PromptName = ?
                    ORDER BY CreatedAt DESC;
                    """,
                    (prompt_name,),
                ).fetchone()
            else:
                row = cursor.execute(
                    """
                    SELECT PromptName, Version, PromptText, Description, Tags, MetadataJson, CreatedAt
                    FROM AI.Prompts
                    WHERE PromptName = ? AND Version = ?;
                    """,
                    (prompt_name, version),
                ).fetchone()

        if row is None:
            return None
        return StoredPromptVersion(
            prompt_name=row.PromptName,
            version=row.Version,
            prompt_text=row.PromptText,
            description=row.Description,
            tags=tuple(tag for tag in (row.Tags or "").split(",") if tag),
            metadata=self._from_json(row.MetadataJson),
            created_at=row.CreatedAt,
        )

    def list_prompts(self, prompt_name: str | None = None) -> tuple[StoredPromptVersion, ...]:
        query = """
            SELECT PromptName, Version, PromptText, Description, Tags, MetadataJson, CreatedAt
            FROM AI.Prompts
        """
        params: tuple[Any, ...] = ()
        if prompt_name is not None:
            query += " WHERE PromptName = ?"
            params = (prompt_name,)
        query += " ORDER BY PromptName ASC, CreatedAt DESC;"

        with self._connect() as connection:
            rows = connection.cursor().execute(query, params).fetchall()

        return tuple(
            StoredPromptVersion(
                prompt_name=row.PromptName,
                version=row.Version,
                prompt_text=row.PromptText,
                description=row.Description,
                tags=tuple(tag for tag in (row.Tags or "").split(",") if tag),
                metadata=self._from_json(row.MetadataJson),
                created_at=row.CreatedAt,
            )
            for row in rows
        )

    def delete_prompt(self, prompt_name: str, version: str | None = None) -> int:
        with self._connect() as connection:
            cursor = connection.cursor()
            if version is None:
                cursor.execute("DELETE FROM AI.Prompts WHERE PromptName = ?;", (prompt_name,))
            else:
                cursor.execute(
                    "DELETE FROM AI.Prompts WHERE PromptName = ? AND Version = ?;",
                    (prompt_name, version),
                )
            connection.commit()
            return cursor.rowcount

    def store_many(self, prompts: Iterable[StoredPromptVersion]) -> int:
        count = 0
        for prompt in prompts:
            self.upsert_prompt(prompt)
            count += 1
        return count

    def _build_connection_string(self) -> str:
        return (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={self._settings.sql_server},{self._settings.sql_port};"
            f"DATABASE={self._settings.sql_database};"
            f"UID={self._settings.sql_user};"
            f"PWD={self._settings.sql_password};"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=5;"
        )

    def _connect(self) -> pyodbc.Connection:
        return pyodbc.connect(self._connection_string)

    def _to_json(self, value: dict[str, Any]) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _from_json(self, value: str | None) -> dict[str, Any]:
        import json

        if not value:
            return {}
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {"raw": value}
        return loaded if isinstance(loaded, dict) else {"value": loaded}
