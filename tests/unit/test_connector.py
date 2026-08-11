"""Tests for connectors/local_files/connector.py -- LocalFilesConnector.run().

Uses a real ConnectorStateStoreRepository against a tmp SQLite file (no
mocking the store itself, consistent with how Raw Store / Connector-State
Store are tested elsewhere) and a stubbed TikaExtractor so no live
container is required.

The scanned directory (files_root) and the connector-state DB's directory
are kept as separate subdirectories of tmp_path -- otherwise the connector
would recursively pick up its own .sqlite tracking file as something to
ingest, since the walk is recursive over root_path.
"""

import os
import time
from pathlib import Path

import pytest

from src.connectors.local_files.connector import LocalFilesConnector
from src.core.enums import ItemStatus
from src.stores.connector_state_store.repository import (
    ConnectorStateStoreRepository,
)


class _StubTikaExtractor:
    """Stands in for TikaExtractor.

    Get_extractor() only needs an
    object with an .extract method; PDF/DOCX/HTML aren't exercised
    directly in these tests since native formats cover every branch of
    run() already.
    """

    def extract(self, path: Path):
        """Raise NotImplementedError because extraction is not exercised here."""
        raise NotImplementedError


@pytest.fixture
def files_root(tmp_path):
    """Provide a temporary directory containing files to scan."""
    root = tmp_path / "files"
    root.mkdir()
    return root


@pytest.fixture
def repo(tmp_path):
    """Provide a temporary connector state repository."""
    db_path = tmp_path / "state" / "connector_state.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    repository = ConnectorStateStoreRepository(db_path)
    yield repository
    repository.close()


@pytest.fixture
def connector(files_root, repo):
    """Provide a LocalFilesConnector using the test fixtures."""
    return LocalFilesConnector(
        root_path=files_root,
        tika_extractor=_StubTikaExtractor(),
        connector_state_repo=repo,
    )


def _run_once(connector):
    """Run the connector once and return all yielded results."""
    return list(connector.run())


# -- first ingest -----------------------------------------------------------


def test_first_ingest_of_new_file_reports_success(files_root, connector):
    """Report success and return a document for a new file."""
    (files_root / "note.txt").write_text("hello world")

    results = _run_once(connector)

    assert len(results) == 1
    result = results[0]
    assert result.status == ItemStatus.SUCCESS
    assert result.document is not None
    assert result.document.raw_content == "hello world"
    assert result.document.source_type == "local_files"
    assert result.error is None


def test_first_ingest_persists_file_state(files_root, connector, repo):
    """Persist the file state after successfully ingesting a new file."""
    path = files_root / "note.txt"
    path.write_text("hello world")

    _run_once(connector)

    state = repo.get_file_state(str(path.resolve()))
    assert state is not None
    assert state.last_size == path.stat().st_size


# -- unchanged re-run --------------------------------------------------------


def test_unchanged_file_on_second_run_reports_unchanged(files_root, connector):
    """Report unchanged when a file has not changed since the previous run."""
    (files_root / "note.txt").write_text("hello world")

    _run_once(connector)  # first run: SUCCESS, persists state
    second = _run_once(connector)

    assert len(second) == 1
    assert second[0].status == ItemStatus.UNCHANGED
    assert second[0].document is None
    assert second[0].error is None


def test_touch_without_content_change_still_reports_unchanged(files_root, connector):
    """Report unchanged when only the file modification time changes."""
    path = files_root / "note.txt"
    path.write_text("hello world")

    _run_once(connector)

    time.sleep(0.01)
    new_time = time.time() + 100
    os.utime(path, (new_time, new_time))  # touch: mtime changes, content doesn't

    results = _run_once(connector)

    assert len(results) == 1
    assert results[0].status == ItemStatus.UNCHANGED


# -- changed content ----------------------------------------------------


def test_changed_content_reports_success_with_new_document(files_root, connector):
    """Report success and return a new document when file content changes."""
    path = files_root / "note.txt"
    path.write_text("version one")

    first = _run_once(connector)
    assert len(first) == 1
    assert first[0].document.raw_content == "version one"

    path.write_text("version two, much longer content than before")
    second = _run_once(connector)

    assert len(second) == 1
    assert second[0].status == ItemStatus.SUCCESS
    assert second[0].document.raw_content == "version two, much longer content than before"
    assert second[0].document.change_token != first[0].document.change_token


# -- unsupported extension -----------------------------------------------


def test_unsupported_extension_reports_failed_permanent(files_root, connector):
    """Report a permanent failure for unsupported file extensions."""
    (files_root / "binary.exe").write_bytes(b"\x00\x01\x02")

    results = _run_once(connector)

    assert len(results) == 1
    assert results[0].status == ItemStatus.FAILED_PERMANENT
    assert results[0].document is None
    assert "exe" in results[0].error.lower() or "extension" in results[0].error.lower()


# -- extraction failure mapping -------------------------------------------


def test_extraction_error_maps_to_failed_transient_on_connectivity_wording(
    files_root, repo
):
    """Map Tika connectivity errors to transient failures."""
    class _FailingTika:
        def extract(self, path):
            raise ConnectionError("tika server connection refused")

    connector = LocalFilesConnector(
        root_path=files_root,
        tika_extractor=_FailingTika(),
        connector_state_repo=repo,
    )
    (files_root / "doc.pdf").write_bytes(b"%PDF-fake")

    results = _run_once(connector)

    assert len(results) == 1
    assert results[0].status == ItemStatus.FAILED_TRANSIENT
    assert results[0].document is None


def test_extraction_error_maps_to_failed_permanent_otherwise(files_root, repo):
    """Map non-connectivity extraction errors to permanent failures."""
    class _FailingTika:
        def extract(self, path):
            raise ValueError("malformed content, cannot parse")

    connector = LocalFilesConnector(
        root_path=files_root,
        tika_extractor=_FailingTika(),
        connector_state_repo=repo,
    )
    (files_root / "doc.pdf").write_bytes(b"%PDF-fake")

    results = _run_once(connector)

    assert len(results) == 1
    assert results[0].status == ItemStatus.FAILED_PERMANENT


# -- directory walk behavior ------------------------------------------------


def test_walk_is_recursive(files_root, connector):
    """Recursively discover files in nested directories."""
    nested = files_root / "sub" / "dir"
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("found me")

    results = _run_once(connector)

    assert len(results) == 1
    assert results[0].document.raw_content == "found me"


def test_directories_themselves_are_skipped(files_root, connector):
    """Skip directories and yield results only for files."""
    (files_root / "just_a_dir").mkdir()
    (files_root / "note.txt").write_text("content")

    results = _run_once(connector)

    assert len(results) == 1  # the directory itself never yields a result


def test_multiple_files_each_get_own_result(files_root, connector):
    """Yield a separate result for each discovered file."""
    (files_root / "a.txt").write_text("a")
    (files_root / "b.txt").write_text("b")
    (files_root / "c.json").write_text("{}")

    results = _run_once(connector)

    assert len(results) == 3
    assert all(r.status == ItemStatus.SUCCESS for r in results)
