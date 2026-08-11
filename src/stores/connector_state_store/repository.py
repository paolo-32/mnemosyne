"""Connector-State Store repository.

Deliberately minimal scope (18.2.1):
cursor + heartbeat/liveness state, keyed by connector_id. Explicitly does
NOT hold per-item change-detection state -- that's derived from the Raw
Store instead (RawStoreRepository.get_latest_current_version).

Crawl-frontier state for continuous-mode scrapers (22.4a.1) will live here
too once the Scrapers connector (Phase 7) needs it -- same table shape,
frontier as an additional opaque JSON blob keyed by connector_id.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.core.models import Cursor, FileState, Heartbeat


_SCHEMA = """
CREATE TABLE IF NOT EXISTS connector_state (
    connector_id             TEXT PRIMARY KEY,
    cursor                   TEXT,
    cursor_updated_at        TEXT,
    expected_interval_seconds INTEGER,
    grace_period_seconds      INTEGER,
    last_report_at            TEXT
);

CREATE TABLE IF NOT EXISTS file_state (
    source_id   TEXT PRIMARY KEY,
    last_mtime  REAL NOT NULL,
    last_size   INTEGER NOT NULL,
    last_hash   TEXT NOT NULL
);
"""


class ConnectorStateStoreRepository:
    """Repository for connector cursor and heartbeat state persistence."""

    def __init__(self, db_path: Path | str) -> None:
        """Initialize the connector-state database.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        # This store's requirements are intentionally trivial (orchestration
        # plan 3) -- schema created inline rather than routed through
        # alembic for Phase 0. Revisit if/when this file gets its own
        # migration history alongside the Raw Store's.
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def _ensure_row(self, connector_id: str) -> None:
        """Create an empty connector-state row if it does not exist.

        Args:
            connector_id: Identifier of the connector.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO connector_state (connector_id) VALUES (?)",
            (connector_id,),
        )

    def get_cursor(self, connector_id: str) -> Cursor | None:
        """Retrieve the stored cursor for a connector.

        Args:
            connector_id: Identifier of the connector.

        Returns:
            The stored cursor, or None if no cursor exists.
        """
        row = self._conn.execute(
            """
            SELECT cursor, cursor_updated_at
            FROM connector_state
            WHERE connector_id = ?
            """,
            (connector_id,),
        ).fetchone()

        if row is None or row["cursor"] is None:
            return None

        return Cursor(
            connector_id=connector_id,
            cursor=row["cursor"],
            updated_at=datetime.fromisoformat(row["cursor_updated_at"]),
        )

    def set_cursor(
        self, connector_id: str, cursor: str, updated_at: datetime
    ) -> None:
        """Store a connector cursor value.

        Args:
            connector_id: Identifier of the connector.
            cursor: Opaque connector-specific cursor value.
            updated_at: Timestamp when the cursor was generated.
        """
        self._ensure_row(connector_id)
        self._conn.execute(
            """
            UPDATE connector_state
            SET cursor = ?, cursor_updated_at = ?
            WHERE connector_id = ?
            """,
            (cursor, updated_at.isoformat(), connector_id),
        )
        self._conn.commit()

    def declare_heartbeat_expectations(
        self,
        connector_id: str,
        expected_interval_seconds: int,
        grace_period_seconds: int,
    ) -> None:
        """Configure heartbeat timeout parameters.

        Args:
            connector_id: Identifier of the connector.
            expected_interval_seconds: Expected heartbeat interval.
            grace_period_seconds: Additional allowed delay before flagging.
        """
        self._ensure_row(connector_id)
        self._conn.execute(
            """
            UPDATE connector_state
            SET expected_interval_seconds = ?, grace_period_seconds = ?
            WHERE connector_id = ?
            """,
            (expected_interval_seconds, grace_period_seconds, connector_id),
        )
        self._conn.commit()

    def report_heartbeat(self, connector_id: str, at: datetime) -> None:
        """Record a heartbeat report from a connector.

        Args:
            connector_id: Identifier of the connector.
            at: Timestamp of the heartbeat.
        """
        self._ensure_row(connector_id)
        self._conn.execute(
            "UPDATE connector_state SET last_report_at = ? WHERE connector_id = ?",
            (at.isoformat(), connector_id),
        )
        self._conn.commit()

    def get_heartbeat(self, connector_id: str) -> Heartbeat | None:
        """Retrieve heartbeat configuration and latest report.

        Args:
            connector_id: Identifier of the connector.

        Returns:
            Heartbeat information, or None if no heartbeat is configured.
        """
        row = self._conn.execute(
            """
            SELECT expected_interval_seconds, grace_period_seconds, last_report_at
            FROM connector_state
            WHERE connector_id = ?
            """,
            (connector_id,),
        ).fetchone()

        if row is None or row["expected_interval_seconds"] is None:
            return None

        return Heartbeat(
            connector_id=connector_id,
            expected_interval_seconds=row["expected_interval_seconds"],
            grace_period_seconds=row["grace_period_seconds"],
            last_report_at=(
                datetime.fromisoformat(row["last_report_at"])
                if row["last_report_at"]
                else None
            ),
        )

    def is_stuck(self, connector_id: str, now: datetime) -> bool:
        """Check whether a connector has exceeded its heartbeat deadline.

        Args:
            connector_id: Identifier of the connector.
            now: Current timestamp used for comparison.

        Returns:
            True if the connector is considered stuck, otherwise False.
        """
        hb = self.get_heartbeat(connector_id)

        if hb is None or hb.last_report_at is None:
            return False

        elapsed = (now - hb.last_report_at).total_seconds()
        return elapsed > (hb.expected_interval_seconds + hb.grace_period_seconds)

    def get_file_state(self, source_id: str) -> FileState | None:
        """Retrieve stored file-state information.

        Args:
            source_id: Identifier of the source file.

        Returns:
            File state information, or None if no state exists.
        """
        row = self._conn.execute(
            """
            SELECT source_id, last_mtime, last_size, last_hash
            FROM file_state
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()

        if row is None:
            return None

        return FileState(
            source_id=row["source_id"],
            last_mtime=row["last_mtime"],
            last_size=row["last_size"],
            last_hash=row["last_hash"],
        )

    def set_file_state(self, state: FileState) -> None:
        """Store file-state information.

        Args:
            state: File state to persist.
        """
        self._conn.execute(
            """
            INSERT INTO file_state (source_id, last_mtime, last_size, last_hash)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (source_id) DO UPDATE SET
            last_mtime = excluded.last_mtime,
            last_size = excluded.last_size,
            last_hash = excluded.last_hash
            """,
            (state.source_id, state.last_mtime, state.last_size, state.last_hash),
        )
        self._conn.commit()
