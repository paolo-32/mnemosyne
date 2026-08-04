"""initial documents table

Revision ID: 0001
Revises:
Create Date: 2026-07-18
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE documents (
            id                  TEXT PRIMARY KEY,
            source_id           TEXT NOT NULL,
            source_type         TEXT NOT NULL,
            change_token        TEXT NOT NULL,
            creation_timestamp  TEXT,
            ingestion_timestamp TEXT NOT NULL,
            metadata            TEXT NOT NULL DEFAULT '{}',
            raw_content         TEXT NOT NULL,
            attachments         TEXT NOT NULL DEFAULT '[]',
            processing_status   TEXT NOT NULL DEFAULT 'queued',
            version             INTEGER NOT NULL DEFAULT 1,
            hash                TEXT NOT NULL,
            provenance          TEXT NOT NULL,
            supersedes          TEXT REFERENCES documents(id),
            status              TEXT NOT NULL DEFAULT 'current'
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_documents_source_id_status ON documents (source_id, status)"
    )
    op.execute(
        "CREATE INDEX idx_documents_source_id_version ON documents (source_id, version)"
    )
    op.execute("CREATE INDEX idx_documents_status ON documents (status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_status")
    op.execute("DROP INDEX IF EXISTS idx_documents_source_id_version")
    op.execute("DROP INDEX IF EXISTS idx_documents_source_id_status")
    op.execute("DROP TABLE IF EXISTS documents")
