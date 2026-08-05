"""Tests for connectors/local_files/format_extractors.py.

Assumes the final shape established in this conversation:
  - ExtractedContent(raw_content: str, metadata: dict) in
    connectors/local_files/models.py
  - extract_plain_text, extract_csv, json_extractor, xml_extractor as
    plain functions in format_extractors.py
  - get_extractor(path, tika_extractor) -> Callable | None dispatch table
  - TikaExtractor imported from connectors/local_files/tika_extractor.py

If any import path here doesn't match the real module layout, only the
import lines need adjusting -- the test bodies exercise behavior, not
file locations.
"""

import json

import pytest

from src.connectors.local_files.format_extractors import (
    extract_csv,
    extract_plain_text,
    get_extractor,
    json_extractor,
    xml_extractor,
)
from src.connectors.local_files.models import ExtractedContent
from src.connectors.local_files.tika_extractor import TikaExtractor


@pytest.fixture
def fake_tika_extractor():
    """Create an unconfigured TikaExtractor stand-in."""
    # Only object identity matters for these tests.
    return TikaExtractor.__new__(TikaExtractor)


# -- extract_plain_text ---------------------------------------------------


def test_extract_plain_text_returns_raw_content(tmp_path):
    """Verify that plain-text files are returned unchanged."""
    path = tmp_path / "note.txt"
    path.write_text("hello world")

    result = extract_plain_text(path)

    assert isinstance(result, ExtractedContent)
    assert result.raw_content == "hello world"
    assert result.metadata == {"format": "txt"}


def test_extract_plain_text_preserves_markdown_structure(tmp_path):
    """Verify that Markdown files are read as plain text."""
    path = tmp_path / "note.md"
    content = "# Heading\n\n- item one\n- item two\n\n```code```"
    path.write_text(content)

    result = extract_plain_text(path)

    # Markdown must be read as plain text, not reconstructed.
    assert result.raw_content == content


# -- extract_csv ----------------------------------------------------------


def test_extract_csv_puts_columns_in_metadata(tmp_path):
    """Verify that CSV headers are stored as metadata."""
    path = tmp_path / "data.csv"
    path.write_text("name,age\nAda,36\nAlan,41\n")

    result = extract_csv(path)

    assert result.metadata == {"columns": ["name", "age"]}
    rows = json.loads(result.raw_content)
    assert rows == [
        {"name": "Ada", "age": "36"},
        {"name": "Alan", "age": "41"},
    ]


def test_extract_csv_empty_file_has_no_rows(tmp_path):
    """Verify that an empty CSV produces no data rows."""
    path = tmp_path / "empty.csv"
    path.write_text("name,age\n")

    result = extract_csv(path)

    assert json.loads(result.raw_content) == []
    assert result.metadata == {"columns": ["name", "age"]}


# -- json_extractor -------------------------------------------------------


def test_json_extractor_object_captures_keys(tmp_path):
    """Verify that JSON object keys are stored as metadata."""
    path = tmp_path / "doc.json"
    path.write_text(json.dumps({"a": 1, "b": 2}))

    result = json_extractor(path)

    # Must remain a string, not a parsed dictionary.
    assert isinstance(result.raw_content, str)
    assert json.loads(result.raw_content) == {"a": 1, "b": 2}
    assert result.metadata == {"keys": ["a", "b"]}


def test_json_extractor_array_does_not_crash(tmp_path):
    """Verify that JSON arrays are handled without key metadata."""
    path = tmp_path / "list.json"
    path.write_text(json.dumps([1, 2, 3]))

    result = json_extractor(path)

    assert json.loads(result.raw_content) == [1, 2, 3]
    assert result.metadata == {"keys": []}


# -- xml_extractor --------------------------------------------------------


def test_xml_extractor_captures_root_tag(tmp_path):
    """Verify that the XML root tag is stored as metadata."""
    path = tmp_path / "doc.xml"
    path.write_text("<root><child>text</child></root>")

    result = xml_extractor(path)

    assert result.metadata == {"root_tag": "root"}
    tree = json.loads(result.raw_content)
    assert tree["tag"] == "root"


def test_xml_extractor_handles_nested_elements(tmp_path):
    """Verify that nested XML elements are represented correctly."""
    path = tmp_path / "nested.xml"
    path.write_text(
        "<root>"
        "<parent attr='1'>"
        "<child>leaf text</child>"
        "</parent>"
        "</root>"
    )

    result = xml_extractor(path)
    tree = json.loads(result.raw_content)

    parent = tree["children"][0]
    assert parent["tag"] == "parent"
    assert parent["attrib"] == {"attr": "1"}

    child = parent["children"][0]
    assert child["tag"] == "child"
    assert child["text"] == "leaf text"


def test_xml_extractor_strips_whitespace_only_text(tmp_path):
    """Verify that whitespace-only XML text nodes become None."""
    path = tmp_path / "pretty.xml"
    path.write_text("<root>\n  <child>\n  </child>\n</root>")

    result = xml_extractor(path)
    tree = json.loads(result.raw_content)

    child = tree["children"][0]
    assert child["text"] is None


# -- get_extractor dispatch table ----------------------------------------


@pytest.mark.parametrize(
    "filename,expected_func",
    [
        ("a.txt", extract_plain_text),
        ("a.md", extract_plain_text),
        ("a.csv", extract_csv),
        ("a.json", json_extractor),
        ("a.xml", xml_extractor),
    ],
)
def test_get_extractor_returns_correct_native_function(
    tmp_path,
    fake_tika_extractor,
    filename,
    expected_func,
):
    """Verify that supported file types map to native extractors."""
    path = tmp_path / filename

    extractor = get_extractor(path, fake_tika_extractor)

    assert extractor == expected_func


@pytest.mark.parametrize("filename", ["a.pdf", "a.docx", "a.html"])
def test_get_extractor_returns_tika_extract_for_tika_formats(
    tmp_path,
    fake_tika_extractor,
    filename,
):
    """Verify that Tika-supported formats use the Tika extractor."""
    path = tmp_path / filename

    extractor = get_extractor(path, fake_tika_extractor)

    assert extractor == fake_tika_extractor.extract


def test_get_extractor_returns_none_for_unsupported_extension(
    tmp_path,
    fake_tika_extractor,
):
    """Verify that unsupported extensions have no extractor."""
    path = tmp_path / "a.exe"

    assert get_extractor(path, fake_tika_extractor) is None


def test_get_extractor_is_case_insensitive(tmp_path, fake_tika_extractor):
    """Verify that extractor dispatch ignores filename case."""
    path = tmp_path / "A.TXT"

    extractor = get_extractor(path, fake_tika_extractor)

    assert extractor == extract_plain_text
