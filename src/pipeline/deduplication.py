"""Pipeline stage: Deduplication (6.3, 6.3.1, 6.3.2).

Scope: catches "the same content under different source_ids", distinct
from change_token comparison (same source, unchanged content, 18.3) and
Entity Resolution (same real-world entity across documents, 13), which
are both handled elsewhere.

Storage boundary: this module is store-agnostic (functional core), it
operates against small Protocols (`ContentHashIndex`, `DuplicateLinkStore`)
rather than importing sqlite3 directly, consistent with the paradigm
table's "no reason to color domain logic with a live store" principle.
Concrete implementations of these Protocols live in
`stores/raw_store/repository.py` against the `duplicate_links` table.

Phase 2 scope note: only Tier 1 (exact content-hash match) is live.
Tier 2 (embedding-similarity near-duplicate confirmation) is a documented
stub until Phase 3 lands real embeddings: see `check_near_duplicate`.
"""

import hashlib
from datetime import datetime, UTC
from typing import Literal

from pydantic import BaseModel

from src.core.models import DuplicateLink
from pipeline.raw_store_contracts import ContentHashIndex, DuplicateLinkStore




def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Result shape. Local to this module, not core/models.py: consumed only
# by pipeline/orchestrator.py, a sibling within the same package, so this
# never crosses a package boundary the way DuplicateLink does (mirrors
# ExtractedContent's local-only placement in connectors/local_files/).
# ---------------------------------------------------------------------------


class DeduplicationResult(BaseModel):
    """Tells the orchestrator whether to skip downstream chunking/extraction/embedding.

    As per 6.3: the second occurrence still gets its own
    Document record for provenance, but piggybacks on the canonical
    original's already-derived chunks/entities/relations).
    """
    is_duplicate: bool
    canonical_source_id: str | None = None
    canonical_version: int | None = None
    match_tier: Literal["exact_hash", "embedding_similarity"] | None = None


# ---------------------------------------------------------------------------
# Tier 1
# ---------------------------------------------------------------------------

def compute_content_hash(normalized_text: str) -> str:
    """Content hash over normalized text (post-6.2).

    Same primitive used for change_token generation elsewhere
    in the spec (SHA-256 over UTF-8 bytes).
    """
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def check_for_duplicate(
    content_hash: str,
    hash_index: ContentHashIndex,
    ) -> tuple[str, int] | None:
    """Tier 1 — exact content-hash match (6.3).

    Returns (source_id, version) of the matched document, or None.
    """
    return hash_index.lookup(content_hash)

# ---------------------------------------------------------------------------
# Tier 2 — near-duplicate confirmation (PHASE 2 STUB)
# ---------------------------------------------------------------------------


def check_near_duplicate(
    *_args: object,
    **_kwargs: object
    ) -> tuple[str, int, float] | None:
    """Tier 2: embedding-similarity near-duplicate confirmation (6.3).

    STUB for Phase 2: EmbeddingGemma/Qdrant don't exist until Phase 3, so
    this always returns None. Consequence: only byte-identical exact
    duplicates are caught in Phase 2; near-duplicates (syndicated
    copies, minor formatting differences, a re-scraped page with a
    different byline) will NOT be detected until this is replaced with a
    real implementation.

    This is a deliberate, documented gap (see Phase 2 handoff doc), not
    a silent bug. Signature intentionally accepts/ignores any arguments
    so call sites in `deduplicate()` below don't need to change shape
    when Phase 3 gives this a real body.
    """
    return None

# ---------------------------------------------------------------------------
# Union-find: canonical resolution with path compression (6.3.2)
# ---------------------------------------------------------------------------


def resolve_canonical(
    source_id: str, link_store: DuplicateLinkStore
) -> tuple[str, int | None]:
    """Union-find `find()` with path compression (6.3.2).

    Walks the duplicate-link chain starting at `source_id` until it
    reaches a source_id with no link row (a canonical root, by the
    table's own definition). Returns (root_source_id, root_version).

    `root_version` is None when `source_id` is itself already canonical
    (no link exists); the caller already knows its own document's
    version in that case, so there's nothing this function needs to
    report.

    Path compression: if the chain was longer than one hop, the
    *originally queried* source_id's link is rewritten to point directly
    at the resolved root, so the next lookup on that same source_id is
    O(1) instead of re-walking the chain. The rewritten link preserves
    the **original** match_tier/similarity_score that source_id was
    first linked under; compression changes the pointer, not the
    reason `source_id` was determined to be a duplicate in the first
    place.
    """
    first_link = link_store.get_link(source_id)
    if first_link is None:
        return source_id, None  # already canonical; nothing to resolve

    current_id = source_id
    last_version = first_link.linked_document_version
    hops = 0
    while True:
        link = link_store.get_link(current_id)
        if link is None:
            break
        current_id = link.linked_source_id
        last_version = link.linked_document_version
        hops += 1

    root_id = current_id

    if hops > 1:
        link_store.set_link(
            DuplicateLink(
                document_source_id=source_id,
                linked_source_id=root_id,
                linked_document_version=last_version,
                match_tier=first_link.match_tier,
                similarity_score=first_link.similarity_score,
                linked_at=_now(),
            )
        )

    return root_id, last_version


def register_duplicate(
    dependent_source_id: str,
    target_source_id: str,
    target_version: int,
    match_tier: Literal["exact_hash", "embedding_similarity"],
    link_store: DuplicateLinkStore,
    similarity_score: float | None = None,
) -> DuplicateLink:
    """Record a newly discovered duplicate relationship (6.3).

    Deliberately does NOT eagerly resolve `target_source_id` to its own
    canonical root before linking. Points directly at whatever it was
    matched against. Chains are allowed to form and are resolved only at
    read time via `resolve_canonical` (6.3.2); eagerly resolving here
    would mean extra lookup work on every single discovery event, which
    the spec explicitly rejects as unnecessary overhead.
    """
    link = DuplicateLink(
        document_source_id=dependent_source_id,
        linked_source_id=target_source_id,
        linked_document_version=target_version,
        match_tier=match_tier,
        similarity_score=similarity_score,
        linked_at=_now(),
    )
    link_store.set_link(link)
    return link


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------


def deduplicate(
    source_id: str,
    normalized_content: str,
    hash_index: ContentHashIndex,
    link_store: DuplicateLinkStore,
) -> DeduplicationResult:
    """Run the full Deduplication stage (6.3) for one document.

    `source_id` is the document currently being processed; it is
    expected to already exist in the Raw Store as its own Document
    record (provenance is preserved regardless of duplicate status;
    6.3 is explicit that a duplicate still gets its own record).
    """
    content_hash = compute_content_hash(normalized_content)

    exact_match = check_for_duplicate(content_hash, hash_index)
    if exact_match is not None:
        target_id, target_version = exact_match
        register_duplicate(
            source_id,
            target_id,
            target_version,
            "exact_hash",
            link_store
            )
        canonical_id, canonical_version = resolve_canonical(source_id, link_store)
        return DeduplicationResult(
            is_duplicate=True,
            canonical_source_id=canonical_id,
            canonical_version=canonical_version,
            match_tier="exact_hash",
        )

    near_match = check_near_duplicate()  # Phase 2 stub — always None
    if near_match is None:
        return DeduplicationResult(is_duplicate=False)

    target_id, target_version, score = near_match
    register_duplicate(
        source_id,
        target_id,
        target_version,
        "embedding_similarity",
        link_store,
        similarity_score=score,
    )
    canonical_id, canonical_version = resolve_canonical(source_id, link_store)
    return DeduplicationResult(
        is_duplicate=True,
        canonical_source_id=canonical_id,
        canonical_version=canonical_version,
        match_tier="embedding_similarity",
    )
