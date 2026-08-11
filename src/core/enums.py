"""Domain enums. No I/O, no dependencies on stores/connectors/pipeline."""

from enum import StrEnum


class ProcessingStatus(StrEnum):
    """Canonical Document processing_status (§5, §18.4)."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class SupersessionStatus(StrEnum):
    """Applies to Documents, Chunks, embeddings, and MENTIONS edges (§16.2, §16.3).

    Deliberately never applies to Entities themselves (§16.4) -- entities have
    no status field; "orphaned" is a derived property, not a stored value.
    """

    CURRENT = "current"
    SUPERSEDED = "superseded"


class IngestionMode(StrEnum):
    """§18.2 -- a behavioral mode, not a connector category."""

    DISCRETE = "discrete"
    CONTINUOUS = "continuous"


class ItemStatus(StrEnum):
    """Per-item outcome reported by a connector invocation (§18.5).

    Deliberately no PARTIAL value -- "was this invocation partial" is a
    derived property computed by inspecting an array of these, never
    self-labeled by the connector.
    """

    SUCCESS = "success"
    UNCHANGED = "unchanged"
    FAILED_TRANSIENT = "failed_transient"
    FAILED_PERMANENT = "failed_permanent"
    REMOVED = "removed"


class Cardinality(StrEnum):
    """Relation-type schema property, not per-instance (§14.4.1)."""

    FUNCTIONAL = "functional"
    MULTI_VALUED = "multi_valued"


class EdgeType(StrEnum):
    """The graph's two structurally distinct edge types (§13.1)."""

    MENTIONS = "mentions"
    RELATION = "relation"
