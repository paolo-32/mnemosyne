from collections.abc import Callable
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from .models import ExtractedContent
from .tika_extractor import Extractor


def extract_plain_text(path: Path) -> ExtractedContent:
    """Extractor for plaintext documents.

    Returns the raw contents of a text file.

    Args:
        path (Path): file's object path.

    Returns:
        ExtractedContent: the file's contents.
    """
    raw_content = path.read_text(encoding="utf-8")
    return ExtractedContent(
        raw_content=raw_content,
        metadata={"format": path.suffix.lstrip(".")},
    )


def extract_markdown_text(path: Path) -> ExtractedContent:
    """Markdown wrapper for extract_plain_text function.

    Returns the contents of a markdown file.

    Args:
        path (Path): file's path object.

    Returns:
        ExtractedContent: the file's contents.
    """
    return extract_plain_text(path)

def extract_csv(path: Path) -> ExtractedContent:
    """Extractor for csv files.

    Returns the raw contents of a csv file.

    Args:
        path (Path): file's object path object

    Returns:
        ExtractedContent: the file's contents
    """
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    return ExtractedContent(
        raw_content=json.dumps(rows),
        metadata = {"columns" : reader.fieldnames},
    )

def json_extractor(path: Path) -> ExtractedContent:
    """Extractor for json files.

    Returns the raw contents of a json file.

    Args:
        path (Path): the file's path object.

    Returns:
        ExtractedContent: the file's contents.
    """
    with path.open(encoding="utf-8") as f:
        parsed = json.load(f)

    keys = list(parsed.keys()) if isinstance(parsed, dict) else []
    return ExtractedContent(
        raw_content=json.dumps(parsed),
        metadata={"keys": keys},
    )

def _element_to_dict(elem: ET.Element) -> dict:
    """Recursive walker for XML files.

    Args:
        elem (ET.Element): XML root.

    Returns:
        dict: file structure.
    """
    node = {
        "tag": elem.tag,
        "attrib": dict(elem.attrib),
        "text": (elem.text or "").strip() or None,
        "children": [_element_to_dict(child) for child in elem],
    }
    return node

def xml_extractor(path: Path) -> ExtractedContent:
    """Extractor for XML files.

    Args:
        path (Path): the file's path object.

    Returns:
        ExtractedContent: the file's contents.
    """
    root = ET.parse(str(path)).getroot()
    tree = _element_to_dict(root)

    return ExtractedContent(
        raw_content=json.dumps(tree),
        metadata={"root_tag": root.tag},
    )

EXTRACTOR_MAP: dict[str, Callable[[Path], ExtractedContent]] = {
    ".md": extract_plain_text,
    ".txt": extract_plain_text,
    ".csv": extract_csv,
    ".json": json_extractor,
    ".xml": xml_extractor,
}


def get_extractor(
    path: Path,
    tika_extractor: Extractor
    ) -> Callable[[Path], ExtractedContent] | None:
    """Routes each document to the appropriate extractor.

    Args:
        path (Path): path object for the file.
        tika_extractor (TikaExtractor): extractor instance.

    Returns:
        Callable[[Path], ExtractedContent] | None: appropriate extractor.
    """
    suffix = path.suffix.lower()

    if suffix in {".pdf", ".docx", ".html"}:
        return tika_extractor.extract

    return EXTRACTOR_MAP.get(suffix)

