from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.parsers.parser_models import ParsedDocument, ParsedObjectType, ParserKind, ParserReference, ParserSummary


@dataclass(frozen=True, slots=True)
class TextParseResult:
    source_path: Path
    title: str
    text: str
    checksum: str
    line_count: int
    character_count: int
    metadata: dict[str, str]
    references: tuple[ParserReference, ...]


class TextParser:
    """Parse plain text and normalized text-like files into a shared document model."""

    def parse_file(self, path: str | Path) -> ParsedDocument:
        source_path = Path(path)
        text = self._load_text(source_path)
        normalized_text = self._normalize_text(text)
        lines = normalized_text.splitlines()
        title = self._extract_title(source_path, lines)
        references = self._extract_references(lines)
        checksum = self._checksum_text(normalized_text)
        metadata = {
            "source_format": source_path.suffix.lower().lstrip(".") or "txt",
            "parser": "text",
        }
        return ParsedDocument(
            source_path=source_path,
            parser_kind=ParserKind.TEXT,
            object_type=ParsedObjectType.DOCUMENT,
            title=title,
            text=normalized_text,
            metadata=metadata,
            references=references,
            checksum=checksum,
            language=self._guess_language(normalized_text),
            page_count=None,
            line_count=len(lines),
            character_count=len(normalized_text),
        )

    def parse_many(self, paths: Iterable[str | Path]) -> tuple[ParsedDocument, ...]:
        return tuple(self.parse_file(path) for path in paths)

    def summarize(self, documents: Iterable[ParsedDocument]) -> ParserSummary:
        docs = tuple(documents)
        if not docs:
            return ParserSummary(
                source_path=Path("<empty>"),
                parser_kind=ParserKind.TEXT,
                object_type=ParsedObjectType.DOCUMENT,
                title="",
                line_count=0,
                character_count=0,
                reference_count=0,
            )
        first = docs[0]
        return ParserSummary(
            source_path=first.source_path,
            parser_kind=ParserKind.TEXT,
            object_type=ParsedObjectType.DOCUMENT,
            title=first.title,
            line_count=sum(doc.line_count or 0 for doc in docs),
            character_count=sum(doc.character_count for doc in docs),
            reference_count=sum(len(doc.references) for doc in docs),
        )

    def _load_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    def _normalize_text(self, text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()

    def _extract_title(self, path: Path, lines: list[str]) -> str:
        if lines:
            first_line = lines[0].strip()
            if first_line:
                return first_line[:120]
        return path.stem

    def _extract_references(self, lines: list[str]) -> tuple[ParserReference, ...]:
        references: list[ParserReference] = []
        seen: set[str] = set()
        for index, line in enumerate(lines, start=1):
            for token in self._split_tokens(line):
                if token in seen:
                    continue
                if self._looks_like_reference(token):
                    seen.add(token)
                    references.append(ParserReference(name=token, kind="text", line=index))
        return tuple(references)

    def _split_tokens(self, text: str) -> list[str]:
        tokens: list[str] = []
        for raw in text.replace("/", " ").replace("\\", " ").replace("-", " ").split():
            token = raw.strip(".,;:()[]{}<>\"'!?")
            if token:
                tokens.append(token)
        return tokens

    def _looks_like_reference(self, token: str) -> bool:
        return len(token) > 2 and any(ch.isalpha() for ch in token)

    def _guess_language(self, text: str) -> str:
        lower = text.lower()
        if any(marker in lower for marker in ("procedure", "function", "select", "begin", "end;")):
            return "sql"
        if any(marker in lower for marker in ("unit ", "procedure ", "function ", "uses ")):
            return "delphi"
        if any(marker in lower for marker in ("# ", "## ", "```", "- ")):
            return "markdown"
        return "unknown"

    def _checksum_text(self, text: str) -> str:
        import hashlib

        digest = hashlib.sha256()
        digest.update(text.encode("utf-8", errors="ignore"))
        return digest.hexdigest()
