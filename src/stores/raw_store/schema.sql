-- Raw Store schema (SQLite).
--
-- This is the sole source of truth (§4.2) -- never hard-deletes, supports
-- soft supersession (§16.2). Every other store is disposable and
-- rebuildable from this one.
--
-- Managed by alembic; this file documents the baseline shape but the
-- authoritative history of changes lives in migrations/versions/.

CREATE TABLE IF NOT EXISTS documents (
    id                  TEXT PRIMARY KEY,
    source_id           TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    change_token        TEXT NOT NULL,
    creation_timestamp  TEXT,              -- ISO8601, nullable (not all sources have one)
    ingestion_timestamp TEXT NOT NULL,     -- ISO8601, set by the pipeline
    metadata            TEXT NOT NULL DEFAULT '{}',   -- JSON
    raw_content         TEXT NOT NULL,
    attachments         TEXT NOT NULL DEFAULT '[]',   -- JSON array of Attachment refs
    processing_status   TEXT NOT NULL DEFAULT 'queued',
    version             INTEGER NOT NULL DEFAULT 1,
    hash                TEXT NOT NULL,
    provenance          TEXT NOT NULL,     -- JSON: connector_id, ingestion_mode, cursor_at_ingestion

    -- Versioning / supersession (§16.2)
    supersedes          TEXT REFERENCES documents(id),
    status              TEXT NOT NULL DEFAULT 'current'  -- 'current' | 'superseded'
);

-- The connector contract's core lookup (§18.2.1): a connector queries the
-- Raw Store for the latest CURRENT version of a given source_id to retrieve
-- its last-known change_token, rather than duplicating that state elsewhere.
-- This index is what makes that lookup efficient.
CREATE INDEX IF NOT EXISTS idx_documents_source_id_status
    ON documents (source_id, status);

-- Point-in-time / version-history queries (§16.5, as_of).
CREATE INDEX IF NOT EXISTS idx_documents_source_id_version
    ON documents (source_id, version);

CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (status);
