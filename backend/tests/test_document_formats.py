"""Format-specific extraction checks for the shared document pipeline."""

import io
import zipfile

import pytest

from app.services.document_processor import extract_document_pages


def _extract(tmp_path, name, content, kind):
    path = tmp_path / name
    path.write_bytes(content)
    return extract_document_pages(str(path), kind)


def test_txt_accepts_utf8_bom_and_cp1252(tmp_path):
    assert "hello" in _extract(tmp_path, "a.txt", b"\xef\xbb\xbfhello", "TXT")[0][1]
    assert "caf\u00e9" in _extract(tmp_path, "b.txt", bytes([99, 97, 102, 0xe9]), "TXT")[0][1]


def test_heading_only_markdown_is_extractable(tmp_path):
    text = "# Heading only"
    assert _extract(tmp_path, "heading.md", text.encode("utf-8"), "MD") == [(None, text)]


def test_normal_markdown_keeps_headings_and_code_blocks(tmp_path):
    text = "# Guide\n\n```py\nprint('ok')\n```"
    assert _extract(tmp_path, "guide.md", text.encode(), "MD")[0][1] == text


def test_csv_keeps_header_and_rows(tmp_path):
    text = "name,team\nAda,Research\n"
    extracted = _extract(tmp_path, "people.csv", text.encode(), "CSV")[0][1]
    assert "Row 1: name | team" in extracted
    assert "Row 2: Ada | Research" in extracted


@pytest.mark.parametrize("kind", ["DOCX", "PPTX", "XLSX"])
def test_office_documents_reject_invalid_or_corrupt_archives(tmp_path, kind):
    with pytest.raises(ValueError):
        _extract(tmp_path, f"bad.{kind.lower()}", b"not a zip archive", kind)


def test_office_archive_expansion_limits_are_checked(tmp_path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "A" * (1024 * 1024))
    with pytest.raises(ValueError, match="compression limits"):
        _extract(tmp_path, "bomb.docx", archive.getvalue(), "DOCX")


def test_empty_text_and_unknown_type_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        _extract(tmp_path, "empty.txt", b"", "TXT")
    with pytest.raises(ValueError, match="Unsupported"):
        _extract(tmp_path, "bad.exe", b"hello", "EXE")
