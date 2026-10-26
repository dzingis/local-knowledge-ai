from __future__ import annotations

from hashlib import sha256
from pathlib import Path


CHUNK_SIZE = 1024 * 1024


def sha256_file(path: str | Path) -> str:
    file_path = Path(path)
    digest = sha256()

    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)

    return digest.hexdigest()
