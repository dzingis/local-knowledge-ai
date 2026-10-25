from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class TextBlock:
    line_number: int
    text: str


@dataclass(slots=True)
class TextDocument:
    path: Path
    blocks: list[TextBlock] = field(default_factory=list)

    @property
    def content(self) -> str:
        return "\n".join(block.text for block in self.blocks)


class TextParser:
    """Parse plain text, Markdown, and HTML as normalized line blocks.

    Milestone 2C keeps this intentionally lightweight so the same normalized
    output can be reused by the chunking and metadata stages.
    """

    def parse(self, path: str | Path, *, encoding: str = "utf-8") -> TextDocument:
        file_path = Path(path)
        text = file_path.read_text(encoding=encoding, errors="ignore")
        lines = text.splitlines()
        blocks = [
            TextBlock(line_number=index + 1, text=line.rstrip())
            for index, line in enumerate(lines)
        ]
        return TextDocument(path=file_path, blocks=blocks)


class MarkdownParser(TextParser):
    """Markdown uses the same normalized line handling for Milestone 2C."""


class HtmlParser(TextParser):
    """HTML is treated as text here; structure refinement comes later."""


def iter_non_empty_lines(document: TextDocument) -> Iterable[TextBlock]:
    for block in document.blocks:
        if block.text.strip():
            yield block
