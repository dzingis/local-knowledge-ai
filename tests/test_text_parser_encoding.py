from __future__ import annotations

from pathlib import Path

from backend.parsers.text_parser import TextParser


def test_text_parser_preserves_croatian_cp1250_characters(tmp_path: Path) -> None:
    source = tmp_path / "croatian.txt"
    source.write_bytes("Magi\u010dni broj je 987654321\r\n".encode("cp1250"))

    parsed = TextParser().parse_file(source)

    assert parsed.text == "Magi\u010dni broj je 987654321"
    assert parsed.title == "Magi\u010dni broj je 987654321"


def test_text_parser_reads_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "utf8-bom.txt"
    source.write_bytes("\ufeffČarobni broj je 987654321".encode("utf-8"))

    parsed = TextParser().parse_file(source)

    assert parsed.text == "Čarobni broj je 987654321"
