import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.core.enums import IngestionMode, SupersessionStatus
from src.core.errors import DocumentNotFoundError, NoOpIngestionError
from src.core.models import CanonicalDocument, Provenance
from src.stores.raw_store.repository import RawStoreRepository

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "stores"
    / "raw_store"
    / "schema.sql"
    )


@pytest.fixture()
def repo(tmp_path):
    """Provide a temporary Raw Store repository for testing."""
    db_path = tmp_path / "raw_store.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    conn.close()

    repository = RawStoreRepository(db_path)
    yield repository
    repository.close()


def make_doc(
    source_id: str,
    change_token: str,
    raw_content: str = "hello"
    ) -> CanonicalDocument:
    """Create a canonical document with test data."""
    return CanonicalDocument(
        id=str(uuid.uuid4()),
        source_id=source_id,
        source_type="local_files",
        change_token=change_token,
        ingestion_timestamp=datetime.now(UTC),
        raw_content=raw_content,
        hash=change_token,
        provenance=Provenance(
            connector_id="local_files_test",
            ingestion_mode=IngestionMode.DISCRETE
            ),
    )


def test_first_ingest_creates_version_1(repo):
    """Create the first document version with version number one."""
    doc = make_doc("file:/a.md", "hash1")
    stored = repo.ingest(doc)

    assert stored.version == 1
    assert stored.supersedes is None
    assert stored.status == SupersessionStatus.CURRENT


def test_unchanged_change_token_is_a_noop(repo):
    """Raise NoOpIngestionError when the change token is unchanged."""
    doc = make_doc("file:/a.md", "hash1")
    repo.ingest(doc)

    dup = make_doc("file:/a.md", "hash1")
    with pytest.raises(NoOpIngestionError):
        repo.ingest(dup)


def test_changed_change_token_creates_new_version_and_supersedes_old(repo):
    """Create a new version and supersede the previous version."""
    v1 = repo.ingest(make_doc("file:/a.md", "hash1", "content v1"))
    v2 = repo.ingest(make_doc("file:/a.md", "hash2", "content v2"))

    assert v2.version == 2
    assert v2.supersedes == v1.id
    assert v2.status == SupersessionStatus.CURRENT

    reloaded_v1 = repo.get_document(v1.id)
    assert reloaded_v1.status == SupersessionStatus.SUPERSEDED


def test_get_latest_current_version_returns_none_for_unknown_source(repo):
    """Return None when no current version exists for the source."""
    assert repo.get_latest_current_version("file:/nonexistent.md") is None


def test_get_latest_current_version_tracks_chain(repo):
    """Return the newest current version for a source."""
    repo.ingest(make_doc("file:/a.md", "hash1"))
    v2 = repo.ingest(make_doc("file:/a.md", "hash2"))

    latest = repo.get_latest_current_version("file:/a.md")
    assert latest.id == v2.id
    assert latest.version == 2


def test_list_versions_returns_full_history_in_order(repo):
    """Return all document versions in ascending version order."""
    v1 = repo.ingest(make_doc("file:/a.md", "hash1"))
    v2 = repo.ingest(make_doc("file:/a.md", "hash2"))
    v3 = repo.ingest(make_doc("file:/a.md", "hash3"))

    versions = repo.list_versions("file:/a.md")
    assert [v.id for v in versions] == [v1.id, v2.id, v3.id]
    assert [v.status for v in versions] == [
        SupersessionStatus.SUPERSEDED,
        SupersessionStatus.SUPERSEDED,
        SupersessionStatus.CURRENT,
    ]


def test_mark_superseded_direct_tombstone(repo):
    """Covers the §18.5 `removed` item-status path.

    source disappeared, no replacement version,
    existing document just gets tombstoned.
    """
    v1 = repo.ingest(make_doc("file:/a.md", "hash1"))
    repo.mark_superseded(v1.id)

    reloaded = repo.get_document(v1.id)
    assert reloaded.status == SupersessionStatus.SUPERSEDED


def test_get_document_raises_for_unknown_id(repo):
    """Raise DocumentNotFoundError when the document ID does not exist."""
    with pytest.raises(DocumentNotFoundError):
        repo.get_document("does-not-exist")
