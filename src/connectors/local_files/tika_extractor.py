import os
from pathlib import Path
from typing import Protocol

from tika import parser

from .models import ExtractedContent


class Extractor(Protocol):
    def extract(self, path: Path) -> ExtractedContent:
        """Extract content and metadata from a file."""
        ...


class TikaExtractor:
    def __init__(self, endpoint: str) -> None:
        """Init TikaExtractor.

        Args:
            endpoint (str): Tika endpoint
        """
        self.endpoint = endpoint
        os.environ["TIKA_SERVER_ENDPOINT"] = endpoint

    def extract(self, path: Path) -> ExtractedContent:
        """Extract the content of a file with tika.

        Args:
            path (Path): path object for the file.

        Returns:
            ExtractedContent: contents of the file.
        """
        parsed = parser.from_file(str(path))
        content = (parsed.get("content") or "").strip()
        metadata = parsed.get("metadata") or {}

        return ExtractedContent(
            raw_content=content,
            metadata=metadata,
        )
