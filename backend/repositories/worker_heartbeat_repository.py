from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import pyodbc

from backend.config.settings import get_settings


@dataclass(frozen=True, slots=True)
class WorkerHeartbeatRecord:
    worker_id: str
    running: bool
    iterations: int
    processed: int
    current_file: str | None
    last_result_file_path: str | None
    last_result_outcome: str | None
    last_heartbeat_at: datetime


@dataclass(frozen=True, slots=True)
class WorkerHeartbeatUpsertResult:
    worker_id: str
    running: bool
    iterations: int
    processed: int
    last_heartbeat_at: datetime


class WorkerHeartbeatRepository:
    """SQL Server-backed repository for background worker heartbeat state."""

    def __init__(self, connection_string: str | None = None) -> None:
        self._settings = get_settings()
        self._connection_string = connection_string or self._build_connection_string()

    def upsert_heartbeat(
        self,
        worker_id: str,
        running: bool,
        iterations: int,
        processed: int,
        current_file: str | None,
        last_result_file_path: str | None,
        last_result_outcome: str | None,
    ) -> WorkerHeartbeatUpsertResult:
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                MERGE AI.WorkerHeartbeat AS target
                USING (SELECT ? AS WorkerId) AS source
                ON target.WorkerId = source.WorkerId
                WHEN MATCHED THEN
                    UPDATE SET
                        Running = ?,
                        Iterations = ?,
                        Processed = ?,
                        CurrentFile = ?,
                        LastResultFilePath = ?,
                        LastResultOutcome = ?,
                        LastHeartbeatAt = ?
                WHEN NOT MATCHED THEN
                    INSERT (
                        WorkerId,
                        Running,
                        Iterations,
                        Processed,
                        CurrentFile,
                        LastResultFilePath,
                        LastResultOutcome,
                        LastHeartbeatAt
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    worker_id,
                    running,
                    iterations,
                    processed,
                    current_file,
                    last_result_file_path,
                    last_result_outcome,
                    now,
                    worker_id,
                    running,
                    iterations,
                    processed,
                    current_file,
                    last_result_file_path,
                    last_result_outcome,
                    now,
                ),
            )
            connection.commit()

        return WorkerHeartbeatUpsertResult(
            worker_id=worker_id,
            running=running,
            iterations=iterations,
            processed=processed,
            last_heartbeat_at=now,
        )

    def get_latest(self, worker_id: str) -> WorkerHeartbeatRecord | None:
        with self._connect() as connection:
            cursor = connection.cursor()
            row = cursor.execute(
                """
                SELECT TOP 1
                    WorkerId,
                    Running,
                    Iterations,
                    Processed,
                    CurrentFile,
                    LastResultFilePath,
                    LastResultOutcome,
                    LastHeartbeatAt
                FROM AI.WorkerHeartbeat
                WHERE WorkerId = ?
                ORDER BY LastHeartbeatAt DESC;
                """,
                (worker_id,),
            ).fetchone()

        if row is None:
            return None

        return WorkerHeartbeatRecord(
            worker_id=row.WorkerId,
            running=bool(row.Running),
            iterations=int(row.Iterations),
            processed=int(row.Processed),
            current_file=row.CurrentFile,
            last_result_file_path=row.LastResultFilePath,
            last_result_outcome=row.LastResultOutcome,
            last_heartbeat_at=row.LastHeartbeatAt,
        )

    def list_heartbeats(self) -> tuple[WorkerHeartbeatRecord, ...]:
        with self._connect() as connection:
            cursor = connection.cursor()
            rows = cursor.execute(
                """
                SELECT
                    WorkerId,
                    Running,
                    Iterations,
                    Processed,
                    CurrentFile,
                    LastResultFilePath,
                    LastResultOutcome,
                    LastHeartbeatAt
                FROM AI.WorkerHeartbeat
                ORDER BY LastHeartbeatAt DESC;
                """
            ).fetchall()

        return tuple(
            WorkerHeartbeatRecord(
                worker_id=row.WorkerId,
                running=bool(row.Running),
                iterations=int(row.Iterations),
                processed=int(row.Processed),
                current_file=row.CurrentFile,
                last_result_file_path=row.LastResultFilePath,
                last_result_outcome=row.LastResultOutcome,
                last_heartbeat_at=row.LastHeartbeatAt,
            )
            for row in rows
        )

    def _connect(self) -> pyodbc.Connection:
        return pyodbc.connect(self._connection_string)

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
