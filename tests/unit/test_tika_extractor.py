"""Tests for connectors/local_files/tika_extractor.py.

Mocks tika.parser.from_file so these run without a live Tika container --
consistent with the orchestration plan's split between Raw Store tests
(real SQLite, no mocks) and lighter-weight unit tests for pieces with an
external service dependency.
"""

import os
from unittest.mock import patch

import pytest

from src.connectors.local_files.models import ExtractedContent
from src.connectors.local_files.tika_extractor import TikaExtractor


def test_sets_server_endpoint_env_var(monkeypatch):
    """Verify that the Tika server endpoint environment variable is set."""
    monkeypatch.delenv("TIKA_SERVER_ENDPOINT", raising=False)

    TikaExtractor(endpoint="http://localhost:9998")

    assert os.environ["TIKA_SERVER_ENDPOINT"] == "http://localhost:9998"


def test_extract_returns_extracted_content(tmp_path):
    """Verify that extracted content and metadata are returned correctly."""
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-fake")

    extractor = TikaExtractor(endpoint="http://localhost:9998")

    with patch("src.connectors.local_files.tika_extractor.parser") as mock_parser:
        mock_parser.from_file.return_value = {
            "content": "  extracted text  ",
            "metadata": {"Content-Type": "application/pdf"},
        }

        result = extractor.extract(path)

    assert isinstance(result, ExtractedContent)
    assert result.raw_content == "extracted text"
    assert result.metadata == {"Content-Type": "application/pdf"}


def test_extract_handles_none_content(tmp_path):
    """Verify that missing content and metadata are normalized."""
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"%PDF-fake")

    extractor = TikaExtractor(endpoint="http://localhost:9998")

    with patch("src.connectors.local_files.tika_extractor.parser") as mock_parser:
        mock_parser.from_file.return_value = {
            "content": None,
            "metadata": None,
        }

        result = extractor.extract(path)

    assert result.raw_content == ""
    assert result.metadata == {}


def test_extract_propagates_connectivity_errors(tmp_path):
    """Verify that connectivity errors are propagated to the caller."""
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-fake")

    extractor = TikaExtractor(endpoint="http://localhost:9998")

    with patch("src.connectors.local_files.tika_extractor.parser") as mock_parser:
        mock_parser.from_file.side_effect = ConnectionError("tika unreachable")

        with pytest.raises(ConnectionError, match="tika unreachable"):
            extractor.extract(path)
