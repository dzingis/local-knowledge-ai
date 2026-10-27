from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from backend.config.settings import Settings, get_settings
from backend.indexer.sql_queue_repository import SqlQueueRepository
from backend.watchers.file_watcher import FileWatcher


logger = logging.getLogger(__name__)


class WatchService:
    def __init__(
        self,
        repository: SqlQueueRepository,
        settings: Settings | None = None,
        watcher_factory: Callable[[str, SqlQueueRepository, Settings], FileWatcher] | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings or get_settings()
        self._watcher_factory = watcher_factory or FileWatcher
        self._watchers: dict[str, FileWatcher] = {}
        self._unavailable: set[str] = set()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._supervisor: threading.Thread | None = None
        self._last_event: str | None = None
        self._last_event_at = 0.0

    @property
    def running(self) -> bool:
        return self._supervisor is not None and self._supervisor.is_alive()

    @property
    def watched_folders(self) -> list[str]:
        with self._lock:
            return list(self._watchers)

    @property
    def last_event(self) -> str | None:
        with self._lock:
            watchers = tuple(self._watchers.values())
            service_event = (self._last_event_at, self._last_event)
        latest = max(
            (
                (watcher.last_event_at, watcher.last_event)
                for watcher in watchers
                if watcher.last_event
            ),
            default=(0.0, None),
        )
        return latest[1] if latest[0] > service_event[0] else service_event[1]

    def start(self) -> None:
        if not self._settings.watch_enabled:
            logger.info('Folder watching is disabled')
            return
        if self.running:
            return

        self._stop_event.clear()
        try:
            self._reconcile()
        except Exception:
            logger.exception('Unable to reconcile configured watch folders during startup')
        self._supervisor = threading.Thread(
            target=self._supervise,
            name='folder-watch-supervisor',
            daemon=True,
        )
        self._supervisor.start()

    async def stop(self) -> None:
        self._stop_event.set()
        supervisor = self._supervisor
        self._supervisor = None
        if supervisor is not None:
            await asyncio.to_thread(supervisor.join, 5)
        with self._lock:
            watchers = tuple(self._watchers.values())
            self._watchers.clear()
        for watcher in watchers:
            try:
                watcher.stop()
            except Exception:
                logger.exception('Unable to stop watcher for folder: %s', watcher.folder)

    def health_status(self, processed_count: int) -> dict[str, object]:
        return {
            'running': self.running,
            'watched_folders': self.watched_folders,
            'queue_size': len(self._repository.get_pending()),
            'processed_count': processed_count,
            'last_event': self.last_event,
        }

    def _supervise(self) -> None:
        while not self._stop_event.wait(self._settings.watch_poll_interval):
            try:
                self._reconcile()
            except Exception:
                logger.exception('Unexpected error while checking watched folders')

    def _reconcile(self) -> None:
        configured = {
            str(Path(folder)): folder
            for folder in self._settings.watch_folders
            if self._folder_type_enabled(folder)
        }
        unavailable_now: set[str] = set()
        with self._lock:
            active_paths = tuple(self._watchers)

        for path in active_paths:
            watcher = self._watchers[path]
            if not Path(path).is_dir() or not watcher.is_alive:
                if not Path(path).is_dir():
                    logger.warning('Network unavailable; watch folder cannot be reached: %s', path)
                    self._unavailable.add(path)
                    unavailable_now.add(path)
                else:
                    logger.warning('Watcher stopped unexpectedly: %s', path)
                try:
                    watcher.stop()
                except Exception:
                    logger.exception('Unable to stop disconnected watcher: %s', path)
                with self._lock:
                    self._watchers.pop(path, None)

        with self._lock:
            active_paths = set(self._watchers)
        for normalized_path, configured_path in configured.items():
            if normalized_path in active_paths or normalized_path in unavailable_now:
                continue
            try:
                watcher = self._watcher_factory(configured_path, self._repository, self._settings)
                watcher.start()
            except (OSError, RuntimeError):
                self._unavailable.add(normalized_path)
                logger.warning(
                    'Network unavailable; will reconnect to watch folder: %s',
                    configured_path,
                    exc_info=True,
                )
                continue
            except Exception:
                logger.exception('Unable to start watcher for folder: %s', configured_path)
                continue
            with self._lock:
                self._watchers[normalized_path] = watcher
            if normalized_path in self._unavailable:
                self._unavailable.discard(normalized_path)
                self._record_event(f'Reconnected to watch folder: {configured_path}')
                logger.info('Reconnected to watch folder: %s', configured_path)
            else:
                self._record_event(f'Watching folder: {configured_path}')
                logger.info('Watching folder: %s', configured_path)

    def _folder_type_enabled(self, folder: str) -> bool:
        normalized = folder.replace('/', '\\')
        is_network = normalized.startswith('\\\\')
        return (
            self._settings.watch_network_enabled
            if is_network
            else self._settings.watch_local_enabled
        )

    def _record_event(self, message: str) -> None:
        with self._lock:
            self._last_event = message
            self._last_event_at = time.monotonic()
