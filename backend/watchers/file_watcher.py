from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from os import stat_result
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.observers.polling import PollingObserver

from backend.config.settings import Settings
from backend.indexer.index_manager import ChangeType, QueueStatus
from backend.indexer.sql_queue_repository import QueueRepositoryRecord, SqlQueueRepository
from backend.watchers.file_event_handler import FileEventHandler
from backend.watchers.hashing import FileFingerprint, FingerprintCache, fingerprint_file


logger = logging.getLogger(__name__)


class FileWatcher:
    def __init__(
        self,
        folder: str | Path,
        repository: SqlQueueRepository,
        settings: Settings,
        observer_factory: Callable[[], BaseObserver] | None = None,
    ) -> None:
        self.folder = Path(folder)
        self._repository = repository
        self._settings = settings
        self._observer_factory = observer_factory or self._create_observer
        self._observer: BaseObserver | None = None
        self._lock = threading.RLock()
        self._timers: dict[str, threading.Timer] = {}
        self._stability: dict[str, tuple[tuple[int, int] | None, float]] = {}
        self._in_progress: set[str] = set()
        self._changed_during_processing: set[str] = set()
        self._fingerprints = FingerprintCache()
        self._stopped = False
        self._last_event: str | None = None
        self._last_event_at = 0.0

    @property
    def is_alive(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    @property
    def last_event(self) -> str | None:
        return self._last_event

    @property
    def last_event_at(self) -> float:
        return self._last_event_at

    def start(self) -> None:
        if not self.folder.is_dir():
            raise FileNotFoundError(f'Watch folder is unavailable: {self.folder}')
        handler = FileEventHandler(
            self._on_file_event,
            self._settings.watch_ignore_patterns,
            self._record_event,
        )
        observer = self._observer_factory()
        observer.schedule(handler, str(self.folder), recursive=self._settings.watch_recursive)
        observer.start()
        self._observer = observer
        self._stopped = False
        logger.info('Watching folder: %s', self.folder)

    @staticmethod
    def _create_observer() -> BaseObserver:
        if Path('/.dockerenv').exists():
            logger.info('Using Watchdog polling observer for Docker-mounted folders')
            return PollingObserver()
        return Observer()

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            timers = tuple(self._timers.values())
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        observer = self._observer
        self._observer = None
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)

    def _on_file_event(self, full_path: str) -> None:
        path = Path(full_path)
        if not path.is_file():
            return
        self._record_event(f'File event: {full_path}')
        self._schedule(path, self._settings.watch_debounce_seconds, reset_stability=True)

    def _record_event(self, message: str) -> None:
        self._last_event = message
        self._last_event_at = time.monotonic()

    def _schedule(self, path: Path, delay: float, reset_stability: bool = False) -> None:
        key = str(path)
        if reset_stability:
            try:
                signature = self._stat_signature(path.stat())
            except OSError:
                signature = None
        with self._lock:
            if self._stopped:
                return
            if key in self._in_progress:
                if reset_stability:
                    self._changed_during_processing.add(key)
                return
            if reset_stability:
                self._stability[key] = (signature, time.monotonic())
            previous = self._timers.pop(key, None)
            if previous is not None:
                previous.cancel()
            timer = threading.Timer(delay, self._check_file, args=(path,))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _check_file(self, path: Path) -> None:
        key = str(path)
        with self._lock:
            self._timers.pop(key, None)
            if self._stopped:
                return
            self._in_progress.add(key)

        reschedule = False
        retry_delay = self._settings.watch_debounce_seconds
        try:
            current_stat = path.stat()
            signature = self._stat_signature(current_stat)
            with self._lock:
                baseline, stable_since = self._stability.get(key, (None, time.monotonic()))

            if baseline is None or signature != baseline:
                with self._lock:
                    self._stability[key] = (signature, time.monotonic())
                reschedule = True
            elif time.monotonic() - stable_since < self._settings.watch_debounce_seconds:
                retry_delay = self._settings.watch_debounce_seconds - (time.monotonic() - stable_since)
                reschedule = True
            else:
                fingerprint = fingerprint_file(path, current_stat.st_mtime)
                final_stat = path.stat()
                if signature != self._stat_signature(final_stat):
                    with self._lock:
                        self._stability[key] = (
                            self._stat_signature(final_stat),
                            time.monotonic(),
                        )
                    reschedule = True
                elif self._is_duplicate(path, fingerprint):
                    self._record_event(f'Duplicate: {path}')
                    logger.info('Duplicate file skipped: %s', path)
                else:
                    record = QueueRepositoryRecord(
                        file_name=path.name,
                        full_path=str(path),
                        extension=path.suffix.lstrip('.'),
                        folder_path=str(path.parent),
                        file_size_bytes=final_stat.st_size,
                        modified_utc=fingerprint.modified_utc,
                        sha256=fingerprint.sha256,
                        status=QueueStatus.PENDING,
                        change_type=ChangeType.NEW,
                        enqueued_at=datetime.now(timezone.utc),
                    )
                    self._repository.enqueue_many([record])
                    self._fingerprints.remember(path, fingerprint)
                    self._record_event(f'Queued file: {path}')
                    logger.info('Queued file: %s', path)
        except FileNotFoundError:
            logger.debug('File disappeared before it could be queued: %s', path)
        except OSError:
            logger.warning('Unable to access watched file: %s', path, exc_info=True)
            with self._lock:
                self._stability[key] = (None, time.monotonic())
            reschedule = True
        except Exception:
            logger.exception('Unable to enqueue watched file: %s', path)
            reschedule = True
        finally:
            with self._lock:
                self._in_progress.discard(key)
                changed_during_processing = key in self._changed_during_processing
                self._changed_during_processing.discard(key)
            if changed_during_processing:
                self._schedule(path, self._settings.watch_debounce_seconds, reset_stability=True)
            elif reschedule:
                self._schedule(path, retry_delay)

    @staticmethod
    def _stat_signature(file_stat: stat_result) -> tuple[int, int]:
        return file_stat.st_size, file_stat.st_mtime_ns

    def _is_duplicate(self, path: Path, fingerprint: FileFingerprint) -> bool:
        if self._fingerprints.is_duplicate(path, fingerprint):
            return True

        stored_fingerprint = self._repository.get_fingerprint(str(path))
        if stored_fingerprint != (fingerprint.sha256, fingerprint.modified_utc):
            return False
        self._fingerprints.remember(path, fingerprint)
        return True
