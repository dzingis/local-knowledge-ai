from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from watchdog.events import FileCreatedEvent

from backend.config.settings import Settings
from backend.indexer.index_manager import ChangeType, QueueStatus
from backend.indexer.sql_queue_repository import QueueRepositoryRecord
from backend.watchers.file_watcher import FileWatcher
from backend.watchers.file_event_handler import FileEventHandler
from backend.watchers.hashing import FileFingerprint, FingerprintCache
from backend.watchers.watch_service import WatchService


class InMemoryQueueRepository:
    def __init__(self) -> None:
        self.records: list[QueueRepositoryRecord] = []

    def enqueue_many(self, items: Iterable[QueueRepositoryRecord]) -> int:
        records = list(items)
        self.records.extend(records)
        return len(records)

    def get_pending(self) -> tuple[QueueRepositoryRecord, ...]:
        return tuple(self.records)

    def get_fingerprint(self, full_path: str) -> tuple[str, datetime] | None:
        record = next((item for item in self.records if item.full_path == full_path), None)
        return (record.sha256, record.modified_utc) if record is not None else None


def _settings(folder: Path, **overrides: object) -> Settings:
    return Settings(
        watch_enabled=True,
        watch_folders=[str(folder)],
        watch_debounce_seconds=0.1,
        watch_poll_interval=30,
        **overrides,
    )


def test_file_is_not_queued_until_debounce_elapsed(tmp_path: Path) -> None:
    file_path = tmp_path / 'document.txt'
    file_path.write_text('stable content', encoding='utf-8')
    repository = InMemoryQueueRepository()
    watcher = FileWatcher(tmp_path, repository, _settings(tmp_path))

    watcher._on_file_event(str(file_path))
    assert repository.records == []
    time.sleep(0.04)
    assert repository.records == []
    file_path.write_text('updated stable content', encoding='utf-8')
    watcher._on_file_event(str(file_path))
    time.sleep(0.07)
    assert repository.records == []

    deadline = time.monotonic() + 1
    while not repository.records and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(repository.records) == 1
    assert repository.records[0].file_name == 'document.txt'


def test_duplicate_fingerprint_is_skipped() -> None:
    cache = FingerprintCache()
    fingerprint = FileFingerprint(
        sha256='same-content-hash',
        modified_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    cache.remember('document.txt', fingerprint)

    assert cache.is_duplicate('document.txt', fingerprint)
    assert not cache.is_duplicate(
        'document.txt',
        FileFingerprint(
            sha256='different-hash',
            modified_utc=fingerprint.modified_utc,
        ),
    )
    assert not cache.is_duplicate(
        'document.txt',
        FileFingerprint(
            sha256=fingerprint.sha256,
            modified_utc=datetime(2025, 1, 2, tzinfo=timezone.utc),
        ),
    )


def test_ignored_patterns_are_not_forwarded(tmp_path: Path) -> None:
    observed: list[str] = []
    handler = FileEventHandler(observed.append, ['*.tmp', '~$*'])

    handler.dispatch(FileCreatedEvent(str(tmp_path / 'partial.TMP')))
    handler.dispatch(FileCreatedEvent(str(tmp_path / '~$document.docx')))

    assert observed == []


def test_stable_file_is_inserted_into_ingestion_queue(tmp_path: Path) -> None:
    file_path = tmp_path / 'document.md'
    file_path.write_text('# Knowledge', encoding='utf-8')
    repository = InMemoryQueueRepository()
    watcher = FileWatcher(tmp_path, repository, _settings(tmp_path))

    watcher._on_file_event(str(file_path))
    deadline = time.monotonic() + 1
    while not repository.records and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(repository.records) == 1
    record = repository.records[0]
    assert record.full_path == str(file_path)
    assert record.status == QueueStatus.PENDING
    assert record.change_type == ChangeType.NEW
    assert len(record.sha256) == 64


def test_unchanged_file_event_is_not_enqueued_twice(tmp_path: Path) -> None:
    file_path = tmp_path / 'document.txt'
    file_path.write_text('same content', encoding='utf-8')
    repository = InMemoryQueueRepository()
    watcher = FileWatcher(tmp_path, repository, _settings(tmp_path))

    watcher._on_file_event(str(file_path))
    deadline = time.monotonic() + 1
    while not repository.records and time.monotonic() < deadline:
        time.sleep(0.01)

    restarted_watcher = FileWatcher(tmp_path, repository, _settings(tmp_path))
    restarted_watcher._on_file_event(str(file_path))
    time.sleep(0.2)

    assert len(repository.records) == 1


def test_network_folder_watcher_reconnects_after_share_returns(tmp_path: Path) -> None:
    share = tmp_path / 'share'
    share.mkdir()
    made_watchers: list[FakeWatcher] = []

    def make_watcher(folder: str, repository: object, settings: Settings) -> FakeWatcher:
        watcher = FakeWatcher(folder)
        made_watchers.append(watcher)
        return watcher

    service = WatchService(
        repository=InMemoryQueueRepository(),  # type: ignore[arg-type]
        settings=_settings(share),
        watcher_factory=make_watcher,  # type: ignore[arg-type]
    )

    service._reconcile()
    assert service.watched_folders == [str(share)]

    share.rmdir()
    service._reconcile()
    assert made_watchers[0].stopped
    assert service.watched_folders == []

    share.mkdir()
    service._reconcile()
    assert len(made_watchers) == 2
    assert service.watched_folders == [str(share)]


class FakeWatcher:
    def __init__(self, folder: str) -> None:
        self.folder = folder
        self.stopped = False
        self.last_event: str | None = None

    @property
    def is_alive(self) -> bool:
        return not self.stopped

    def start(self) -> None:
        if not Path(self.folder).is_dir():
            raise FileNotFoundError(self.folder)

    def stop(self) -> None:
        self.stopped = True
