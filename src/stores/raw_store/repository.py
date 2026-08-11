"""Raw Store repository.

Plain sqlite3 -- no ORM.
Alembic (configured separately in migrations/) owns schema evolution;
this module only ever issues DML against tables that already exist.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.core.enums import SupersessionStatus
from src.core.errors import DocumentNotFoundError, NoOpIngestionError
from src.core.models import CanonicalDocument, Provenance


def _row_to_document(row: sqlite3.Row) -> CanonicalDocument:
    return CanonicalDocument(
        id=row["id"],
        source_id=row["source_id"],
        source_type=row["source_type"],
        change_token=row["change_token"],
        creation_timestamp=row["creation_timestamp"],
        ingestion_timestamp=row["ingestion_timestamp"],
        metadata=json.loads(row["metadata"]),
        raw_content=row["raw_content"],
        attachments=json.loads(row["attachments"]),
        processing_status=row["processing_status"],
        version=row["version"],
        hash=row["hash"],
        provenance=Provenance(**json.loads(row["provenance"])),
        supersedes=row["supersedes"],
        status=SupersessionStatus(row["status"]),
    )


class RawStoreRepository:
    def __init__(self, db_path: Path | str) -> None:
        """Initialize the repository and connect to the SQLite database."""
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        """Close the connection to the SQL database."""
        self._conn.close()

    # -- internal helpers ---------------------------------------------

    def _insert_row(self, doc: CanonicalDocument) -> None:
        self._conn.execute(
            """
            INSERT INTO documents (
                id, source_id, source_type, change_token,
                creation_timestamp, ingestion_timestamp, metadata,
                raw_content, attachments, processing_status, version,
                hash, provenance, supersedes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc.id,
                doc.source_id,
                doc.source_type,
                doc.change_token,
                doc.creation_timestamp.isoformat() if doc.creation_timestamp else None,
                doc.ingestion_timestamp.isoformat(),
                json.dumps(doc.metadata),
                doc.raw_content,
                json.dumps([a.model_dump() for a in doc.attachments]),
                doc.processing_status.value
                if hasattr(doc.processing_status, "value")
                else doc.processing_status,
                doc.version,
                doc.hash,
                doc.provenance.model_dump_json(),
                doc.supersedes,
                doc.status.value if hasattr(doc.status, "value") else doc.status,
            ),
        )

    # -- reads -----------------------------------------------------------

    def get_document(self, document_id: str) -> CanonicalDocument:
        """Return a document by ID or raise DocumentNotFoundError if missing."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            raise DocumentNotFoundError(document_id)
        return _row_to_document(row)

    def get_latest_current_version(self, source_id: str) -> CanonicalDocument | None:
        """Backing the connector contract's core lookup (18.2.1).

        A connector's two-tier cheap-filter pattern needs the last-known
        change_token for a source_id, derived from here rather than
        duplicated in the connector-state store.
        """
        row = self._conn.execute(
            """
            SELECT * FROM documents
            WHERE source_id = ? AND status = 'current'
            ORDER BY version DESC LIMIT 1
            """,
            (source_id,),
        ).fetchone()
        return _row_to_document(row) if row else None

    def list_versions(self, source_id: str) -> list[CanonicalDocument]:
        """Return all document versions for a source in ascending order."""
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE source_id = ? ORDER BY version ASC",
            (source_id,),
        ).fetchall()
        return [_row_to_document(r) for r in rows]

    def as_of(self, source_id: str, timestamp: datetime) -> CanonicalDocument | None:
        """Point-in-time reconstruction (§16.5).

        The latest version whose ingestion_timestamp
        is <= the given timestamp, current or not.
        """
        row = self._conn.execute(
            """
            SELECT * FROM documents
            WHERE source_id = ? AND ingestion_timestamp <= ?
            ORDER BY version DESC LIMIT 1
            """,
            (source_id, timestamp.isoformat()),
        ).fetchone()
        return _row_to_document(row) if row else None

    # -- writes ------------------------------------------------------------

    def ingest(self, doc: CanonicalDocument) -> CanonicalDocument:
        """Apply change detection and supersession rules.

        This centralizes the change-detection and supersession logic so every
        connector category follows the same behavior:

        * No prior version for ``source_id``: insert as version 1.
        * Matching ``change_token``: raise ``NoOpIngestionError``.
        * Different ``change_token``: create a new version and supersede the
          previous version.

        The caller must already have assigned ``doc.id`` and
        ``doc.ingestion_timestamp``. The version is recomputed here, so any
        caller-supplied value for an existing ``source_id`` is not trusted.
        """
        latest = self.get_latest_current_version(doc.source_id)

        if latest is None:
            new_doc = doc.model_copy(update={"version": 1, "supersedes": None})
            self._insert_row(new_doc)
            self._conn.commit()
            return new_doc

        if latest.change_token == doc.change_token:
            raise NoOpIngestionError(
                f"source_id={doc.source_id!r}"
                "change_token unchanged; no new version created"
            )

        new_doc = doc.model_copy(
            update={"version": latest.version + 1, "supersedes": latest.id}
        )
        self._conn.execute(
            "UPDATE documents SET status = 'superseded' WHERE id = ?", (latest.id,)
        )
        self._insert_row(new_doc)
        self._conn.commit()
        return new_doc

    def mark_superseded(self, document_id: str) -> None:
        """Direct tombstone, e.g. for the `removed` item status (18.5).

        The source is gone, so its current Document is superseded without
        a replacement version being created.
        """
        self._conn.execute(
            "UPDATE documents SET status = 'superseded' WHERE id = ?", (document_id,)
        )
        self._conn.commit()
