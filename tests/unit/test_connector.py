"""Tests for connectors/local_files/connector.py -- LocalFilesConnector.run().

Uses a real ConnectorStateStoreRepository against a tmp SQLite file (no
mocking the store itself, consistent with how Raw Store / Connector-State
Store are tested elsewhere) and a stubbed TikaExtractor so no live
container is required.
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
    """Stub implementation of the Tika extractor."""

    def extract(self, path: Path):
        """Raise because this stub should never be invoked."""
        raise NotImplementedError


@pytest.fixture
def repo(tmp_path):
    """Create a temporary connector-state repository."""
    db_path = tmp_path / "connector_state.sqlite"
    repository = ConnectorStateStoreRepository(db_path)
    yield repository
    repository.close()


@pytest.fixture
def connector(tmp_path, repo):
    """Create a LocalFilesConnector backed by a temporary repository."""
    return LocalFilesConnector(
        root_path=tmp_path,
        tika_extractor=_StubTikaExtractor(),
        connector_state_repo=repo,
    )


def _run_once(connector):
    """Execute the connector once and collect all yielded results."""
    return list(connector.run())


# -- first ingest -----------------------------------------------------------


def test_first_ingest_of_new_file_reports_success(tmp_path, connector):
    """Verify that a newly discovered file is ingested successfully."""
    (tmp_path / "note.txt").write_text("hello world")

    results = _run_once(connector)

    assert len(results) == 1
    result = results[0]
    assert result.status == ItemStatus.SUCCESS
    assert result.document is not None
    assert result.document.raw_content == "hello world"
    assert result.document.source_type == "local_files"
    assert result.error is None


def test_first_ingest_persists_file_state(tmp_path, connector, repo):
    """Verify that ingesting a file stores its tracking state."""
    path = tmp_path / "note.txt"
    path.write_text("hello world")

    _run_once(connector)

    state = repo.get_file_state(str(path.resolve()))
    assert state is not None
    assert state.last_size == path.stat().st_size


# -- unchanged re-run -------------------------------------------------------


def test_unchanged_file_on_second_run_reports_unchanged(tmp_path, connector):
    """Verify that unchanged files are reported as unchanged."""
    (tmp_path / "note.txt").write_text("hello world")

    _run_once(connector)
    second = _run_once(connector)

    assert len(second) == 1
    assert second[0].status == ItemStatus.UNCHANGED
    assert second[0].document is None
    assert second[0].error is None


def test_touch_without_content_change_still_reports_unchanged(
    tmp_path,
    connector,
):
    """Verify that touching a file does not report a content change."""
    path = tmp_path / "note.txt"
    path.write_text("hello world")

    _run_once(connector)

    time.sleep(0.01)
    new_time = time.time() + 100
    os.utime(path, (new_time, new_time))

    results = _run_once(connector)

    assert results[0].status == ItemStatus.UNCHANGED


# -- changed content --------------------------------------------------------


def test_changed_content_reports_success_with_new_document(
    tmp_path,
    connector,
):
    """Verify that modified content produces a new successful ingestion."""
    path = tmp_path / "note.txt"
    path.write_text("version one")

    first = _run_once(connector)
    assert first[0].document.raw_content == "version one"

    updated = "version two, much longer content than before"
    path.write_text(updated)

    second = _run_once(connector)

    assert len(second) == 1
    assert second[0].status == ItemStatus.SUCCESS
    assert second[0].document.raw_content == updated
    assert second[0].document.change_token != first[0].document.change_token


# -- unsupported extension -------------------------------------------------


def test_unsupported_extension_reports_failed_permanent(
    tmp_path,
    connector,
):
    """Verify that unsupported file types fail permanently."""
    (tmp_path / "binary.exe").write_bytes(b"\x00\x01\x02")

    results = _run_once(connector)

    assert len(results) == 1
    assert results[0].status == ItemStatus.FAILED_PERMANENT
    assert results[0].document is None
    assert (
        "exe" in results[0].error.lower()
        or "extension" in results[0].error.lower()
    )


# -- extraction failure mapping --------------------------------------------


def test_extraction_error_maps_to_failed_transient_on_connectivity_wording(
    tmp_path,
    repo,
):
    """Verify that connectivity errors map to FAILED_TRANSIENT."""

    class _FailingTika:
        def extract(self, path: Path):
            raise ConnectionError("tika server connection refused")

    connector = LocalFilesConnector(
        root_path=tmp_path,
        tika_extractor=_FailingTika(),
        connector_state_repo=repo,
    )

    (tmp_path / "doc.pdf").write_bytes(b"%PDF-fake")

    results = _run_once(connector)

    assert results[0].status == ItemStatus.FAILED_TRANSIENT
    assert results[0].document is None


def test_extraction_error_maps_to_failed_permanent_otherwise(
    tmp_path,
    repo,
):
    """Verify that non-connectivity errors map to FAILED_PERMANENT."""

    class _FailingTika:
        def extract(self, path: Path):
            raise ValueError("malformed content, cannot parse")

    connector = LocalFilesConnector(
        root_path=tmp_path,
        tika_extractor=_FailingTika(),
        connector_state_repo=repo,
    )

    (tmp_path / "doc.pdf").write_bytes(b"%PDF-fake")

    results = _run_once(connector)

    assert results[0].status == ItemStatus.FAILED_PERMANENT


# -- directory walk behavior -----------------------------------------------


def test_walk_is_recursive(tmp_path, connector):
    """Verify that files in nested directories are discovered."""
    nested = tmp_path / "sub" / "dir"
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("found me")

    results = _run_once(connector)

    assert len(results) == 1
    assert results[0].document.raw_content == "found me"


def test_directories_themselves_are_skipped(tmp_path, connector):
    """Verify that directories do not produce connector results."""
    (tmp_path / "just_a_dir").mkdir()
    (tmp_path / "note.txt").write_text("content")

    results = _run_once(connector)

    assert len(results) == 1


def test_multiple_files_each_get_own_result(tmp_path, connector):
    """Verify that each discovered file yields a separate result."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "c.json").write_text("{}")

    results = _run_once(connector)

    assert len(results) == 3
    assert all(result.status == ItemStatus.SUCCESS for result in results)
