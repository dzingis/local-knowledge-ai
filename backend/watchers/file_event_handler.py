from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, PatternMatchingEventHandler


logger = logging.getLogger(__name__)


class FileEventHandler(PatternMatchingEventHandler):
    def __init__(
        self,
        on_file_event: Callable[[str], None],
        ignore_patterns: list[str],
        on_ignored_file: Callable[[str], None] | None = None,
    ) -> None:
        self._on_file_event = on_file_event
        self._on_ignored_file = on_ignored_file
        self._watch_ignore_patterns = tuple(ignore_patterns)
        super().__init__(
            patterns=['*'],
            ignore_patterns=[],
            ignore_directories=True,
            case_sensitive=False,
        )

    def dispatch(self, event: FileSystemEvent) -> None:
        target_path = getattr(event, 'dest_path', '') or event.src_path
        if self._is_ignored(target_path):
            logger.info('Ignored file: %s', target_path)
            if self._on_ignored_file is not None:
                self._on_ignored_file(f'Ignored file: {target_path}')
            return
        super().dispatch(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._on_file_event(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._on_file_event(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        destination = getattr(event, 'dest_path', None)
        if destination:
            self._on_file_event(destination)

    def _is_ignored(self, path: str) -> bool:
        name = Path(path).name
        return any(
            fnmatch.fnmatchcase(path.casefold(), pattern.casefold())
            or fnmatch.fnmatchcase(name.casefold(), pattern.casefold())
            for pattern in self._watch_ignore_patterns
        )
