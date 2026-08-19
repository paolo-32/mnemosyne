"""Domain models.

No I/O -- pure data shapes validated at construction time.

core/ has zero imports from stores/, connectors/, or pipeline/. Everything
else in the codebase depends inward on this module. This is what keeps the
Graph Store Adapter's boundary real: resolution/pipeline code must only ever
import from here, never a LadybugDB or Qdrant type directly.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from src.core.enums import (
    Cardinality,
    IngestionMode,
    ItemStatus,
    ProcessingStatus,
    SupersessionStatus,
)

# ---------------------------------------------------------------------------
# Canonical Document (5, 18.4)
# ---------------------------------------------------------------------------


class Attachment(BaseModel):
    """A reference to attachment content stored on disk.

    Only a path/hash reference lives in the Raw Store row itself.
    The binary content lives under the content-addressed convention in
    stores/raw_store/attachments.py.
    """

    filename: str
    media_type: str | None = None
    hash: str  # sha256 hex digest; also the content-addressing key on disk
    size_bytes: int | None = None


class Provenance(BaseModel):
    """18.4 provenance block.

    Populated by the connector (connector_id, ingestion_mode), except
    cursor_at_ingestion, which is pipeline-populated since it depends on
    when ingestion actually runs (present only for continuous mode).
    """

    connector_id: str
    ingestion_mode: IngestionMode
    cursor_at_ingestion: str | None = None  # present only for continuous mode


class CanonicalDocument(BaseModel):
    """The universal currency of the platform.

    Every connector emits this shape regardless of source type;
    no component downstream of ingestion needs to know where the data originated.

    Field provenance (18.4):
      connector-populated: source_id, source_type, change_token,
        creation_timestamp, metadata, raw_content, attachments, hash
      pipeline-populated: id, ingestion_timestamp, processing_status,
        version, provenance.cursor_at_ingestion
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    source_type: str
    change_token: str
    creation_timestamp: datetime | None = None
    ingestion_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
        )
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_content: str
    attachments: list[Attachment] = Field(default_factory=list)
    processing_status: ProcessingStatus = ProcessingStatus.QUEUED
    version: int = 1
    hash: str
    provenance: Provenance

    # Versioning / supersession (16.2) -- not part of 18.4's wire shape,
    # but tracked on the stored row.
    supersedes: str | None = None  # prior version's document id
    status: SupersessionStatus = SupersessionStatus.CURRENT


class DuplicateLink(BaseModel):
    """A live duplicate relationship between two documents (As per 6.3, 6.3.1, 6.3.2).

    One row per *dependent* document, a source_id with no row is, by definition,
    a canonical root (6.3.2's union-find base case: absence of a link IS
    "this is canonical", not a separate flag).

    'linked_source_id' + 'linked_document_version' together pin the exact version
    this link was last confirmed/path-compressed against, per 6.3.1's explicit
    requirement to store "which version", not just a stable identity reference.

    This mirrors the document_id/document_version split already used
    by Chunk records (17.2) rather than inventing a new convention.
    """
    document_source_id: str
    linked_source_id: str
    linked_document_version: int
    match_tier: Literal["exact_hash", "embedding_similarity"]
    similarity_score: float | None = None
    linked_at: datetime

    @model_validator(mode="after")
    def _check_similarity_score_shape(self) -> DuplicateLink:
        if self.match_tier == "exact_hash" and self.similarity_score is not None:
            raise ValueError("exact_hash links must not carry a similarity_score")
        if self.match_tier == "embedding_similarity" and self.similarity_score is None:
            raise ValueError("embedding_similarity links must carry a similarity_score")
        return self

# ---------------------------------------------------------------------------
# Confidence fields (13.4)
# ---------------------------------------------------------------------------


class MentionConfidence(BaseModel):
    """Three distinct measurements, never blended into one score (13.4)."""

    extraction_confidence: float = Field(ge=0.0, le=1.0)
    resolution_confidence: float = Field(ge=0.0, le=1.0)
    source_trust: float = Field(ge=0.0, le=1.0)


class RelationConfidence(BaseModel):
    """RELATION edges carry two of the three fields.

    No resolution_confidence, since relations are not
    deduplicated against existing relations in v1 (17.3 open items).
    """

    extraction_confidence: float = Field(ge=0.0, le=1.0)
    source_trust: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Entity / Mention / Relation (13.1)
# ---------------------------------------------------------------------------


class Entity(BaseModel):
    """A canonical node representing a real-world thing.

    One entity, one node, no duplicates (13.1).
    Entities carry no status/superseded field.
    "orphaned" is a derived property (16.4), never stored here.
    """

    id: str
    entity_type: str
    properties: dict[str, Any] = Field(default_factory=dict)

    # Set only when this entity has been absorbed via merge_entities (13.3.4).
    # Extends the tombstone pattern from 16 without introducing a Document-style
    # `superseded` status onto Entities themselves.
    superseded_into: str | None = None


class Offset(BaseModel):
    start: int
    end: int


class Mention(BaseModel):
    """(Chunk) --[MENTIONS]--> (Entity) edge (13.1).

    Provenance-flavored, not semantic-flavored;
    kept structurally distinct from Relation.
    """

    id: str
    chunk_id: str
    entity_id: str
    offset: Offset
    confidence: MentionConfidence
    status: SupersessionStatus = SupersessionStatus.CURRENT


class Relation(BaseModel):
    """(Entity) --[RELATION]--> (Entity) edge (13.1).

    Semantic-flavored.
    """

    id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    cardinality: Cardinality
    confidence: RelationConfidence
    status: SupersessionStatus = SupersessionStatus.CURRENT


# ---------------------------------------------------------------------------
# Connector-state store shapes (18.2, 18.2.1, 18.2.2)
# ---------------------------------------------------------------------------


class Cursor(BaseModel):
    """Connector-defined opaque state (18.2).

    The pipeline stores and returns this verbatim;
    only the connector interprets its contents.
    """

    connector_id: str
    cursor: str | None = None
    updated_at: datetime


class Heartbeat(BaseModel):
    """Stuck-connector detection state (18.2.2)."""

    connector_id: str
    expected_interval_seconds: int
    grace_period_seconds: int
    last_report_at: datetime | None = None


class FileState(BaseModel):
    """Change detection state model for local files connector."""

    source_id: str
    last_mtime: float
    last_size: int
    last_hash: str


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

class ConnectorItemResult(BaseModel):
    source_id: str
    status: ItemStatus
    document: CanonicalDocument | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> ConnectorItemResult:
        if self.status == ItemStatus.SUCCESS:
            if self.document is None:
                raise ValueError("success results must carry a document")
            if self.error is not None:
                raise ValueError("success results must not carry an error")
        elif self.status == ItemStatus.UNCHANGED:
            if self.document is not None or self.error is not None:
                raise ValueError(
                    "unchanged results must carry neither document nor error"
                    )
        else:  # FAILED_TRANSIENT, FAILED_PERMANENT, REMOVED
            if self.error is None:
                raise ValueError(f"{self.status} results must carry an error message")
            if self.document is not None:
                raise ValueError(f"{self.status} results must not carry a document")
        return self
