from datetime import datetime, UTC

import pytest
from pydantic import ValidationError

from src.core.models import DuplicateLink
from src.pipeline.deduplication import (
    DeduplicationResult,
    check_for_duplicate,
    check_near_duplicate,
    compute_content_hash,
    deduplicate,
    register_duplicate,
    resolve_canonical,
)


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class FakeContentHashIndex:
    """Fake ContentHashIndex — a plain dict of hash -> (source_id, version)."""

    def __init__(self, mapping: dict[str, tuple[str, int]] | None = None):
        """Initialize the fake index with an optional hash mapping."""
        self._mapping = dict(mapping or {})

    def lookup(self, content_hash: str) -> tuple[str, int] | None:
        """Look up a content hash and return its associated document."""
        return self._mapping.get(content_hash)


class FakeDuplicateLinkStore:
    """Fake DuplicateLinkStore.

    A plain dict of source_id -> DuplicateLink.
    Tracks every set_link call so tests can assert on write/compression
    behavior, not just final state.
    """

    def __init__(self):
        """Initialize an empty duplicate-link store."""
        self._links: dict[str, DuplicateLink] = {}
        self.set_calls: list[str] = []

    def get_link(self, source_id: str) -> DuplicateLink | None:
        """Return the duplicate link associated with a source ID."""
        return self._links.get(source_id)

    def set_link(self, link: DuplicateLink) -> None:
        """Store a duplicate link and record the write operation."""
        self._links[link.document_source_id] = link
        self.set_calls.append(link.document_source_id)


def _link(
    document_source_id: str,
    linked_source_id: str,
    linked_document_version: int,
    match_tier: str = "exact_hash",
    similarity_score: float | None = None,
) -> DuplicateLink:
    """Create a DuplicateLink test fixture."""
    return DuplicateLink(
        document_source_id=document_source_id,
        linked_source_id=linked_source_id,
        linked_document_version=linked_document_version,
        match_tier=match_tier,
        similarity_score=similarity_score,
        linked_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# DuplicateLink model validation (exercised heavily here; belongs alongside
# a future test_models.py if one is split out, kept here for now since this
# is the primary consumer)
# ---------------------------------------------------------------------------


class TestDuplicateLinkValidation:
    def test_exact_hash_rejects_similarity_score(self):
        """Verify that exact-hash links reject similarity scores."""
        with pytest.raises(ValidationError):
            _link("a", "b", 1, match_tier="exact_hash", similarity_score=0.9)

    def test_embedding_similarity_requires_similarity_score(self):
        """Verify that embedding-similarity links require a score."""
        with pytest.raises(ValidationError):
            _link("a", "b", 1, match_tier="embedding_similarity", similarity_score=None)

    def test_exact_hash_without_score_is_valid(self):
        """Verify that exact-hash links are valid without a similarity score."""
        link = _link("a", "b", 1, match_tier="exact_hash")
        assert link.similarity_score is None

    def test_embedding_similarity_with_score_is_valid(self):
        """Verify that embedding-similarity links accept a similarity score."""
        link = _link(
            "a", "b", 1,
            match_tier="embedding_similarity",
            similarity_score=0.92
            )
        assert link.similarity_score == 0.92


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_deterministic(self):
        """Verify that identical content produces identical hashes."""
        assert (
            compute_content_hash("hello world")
            == compute_content_hash("hello world")
            )

    def test_different_content_different_hash(self):
        """Verify that different content produces different hashes."""
        assert compute_content_hash("hello") != compute_content_hash("world")

    def test_is_hex_sha256(self):
        """Verify that the computed hash is a valid SHA-256 hex digest."""
        h = compute_content_hash("hello world")
        assert len(h) == 64
        int(h, 16)  # raises if not valid hex


# ---------------------------------------------------------------------------
# check_for_duplicate (Tier 1)
# ---------------------------------------------------------------------------


class TestCheckForDuplicate:
    def test_match_found(self):
        """Verify that an existing content hash returns its document."""
        index = FakeContentHashIndex({"abc123": ("doc-a", 3)})
        assert check_for_duplicate("abc123", index) == ("doc-a", 3)

    def test_no_match(self):
        """Verify that an unknown content hash returns no match."""
        index = FakeContentHashIndex()
        assert check_for_duplicate("abc123", index) is None


# ---------------------------------------------------------------------------
# check_near_duplicate (Tier 2 — Phase 2 stub)
# ---------------------------------------------------------------------------


class TestCheckNearDuplicateStub:
    def test_always_returns_none_no_args(self):
        """Verify that the Phase 2 near-duplicate stub returns None."""
        assert check_near_duplicate() is None

    def test_always_returns_none_with_args(self):
        """Verify that the stub returns None when given positional arguments."""
        assert check_near_duplicate("some_hash", object(), object()) is None

    def test_always_returns_none_with_kwargs(self):
        """Verify that the stub returns None with keyword arguments."""
        assert check_near_duplicate(embedding=[0.1, 0.2], index=object()) is None


# ---------------------------------------------------------------------------
# register_duplicate
# ---------------------------------------------------------------------------


class TestRegisterDuplicate:
    def test_creates_exact_hash_link(self):
        """Verify that an exact-hash duplicate link is created correctly."""
        store = FakeDuplicateLinkStore()
        link = register_duplicate("dep", "target", 2, "exact_hash", store)
        assert link.document_source_id == "dep"
        assert link.linked_source_id == "target"
        assert link.linked_document_version == 2
        assert link.match_tier == "exact_hash"
        assert link.similarity_score is None
        assert store.get_link("dep") == link

    def test_creates_embedding_similarity_link_with_score(self):
        """Verify that an embedding-similarity link stores its score."""
        store = FakeDuplicateLinkStore()
        link = register_duplicate(
            "dep", "target", 2, "embedding_similarity", store, similarity_score=0.95
        )
        assert link.similarity_score == 0.95

    def test_points_directly_at_target_no_eager_resolution(self):
        """Verify that registration does not eagerly resolve duplicate chains."""
        # target is itself already a duplicate of something else — register
        # must NOT chase that chain; it points at exactly what was passed.
        store = FakeDuplicateLinkStore()
        store.set_link(_link("target", "real_root", 1))
        store.set_calls.clear()

        link = register_duplicate("dep", "target", 5, "exact_hash", store)

        assert link.linked_source_id == "target"  # not "real_root"
        assert store.set_calls == ["dep"]  # only one write, no chain-chasing

    def test_overwrite_semantics(self):
        """Verify that registering a duplicate overwrites an existing link."""
        store = FakeDuplicateLinkStore()
        register_duplicate("dep", "target-1", 1, "exact_hash", store)
        register_duplicate("dep", "target-2", 4, "exact_hash", store)
        assert store.get_link("dep").linked_source_id == "target-2"


# ---------------------------------------------------------------------------
# resolve_canonical (union-find find() with path compression, §6.3.2)
# ---------------------------------------------------------------------------


class TestResolveCanonical:
    def test_already_canonical_no_link(self):
        """Verify that a canonical document requires no link or write."""
        store = FakeDuplicateLinkStore()
        root_id, version = resolve_canonical("solo-doc", store)
        assert root_id == "solo-doc"
        assert version is None
        assert store.set_calls == []  # no write for an already-canonical doc

    def test_single_hop_no_compression_needed(self):
        """Verify that a single-hop duplicate resolves without rewriting."""
        store = FakeDuplicateLinkStore()
        store.set_link(_link("B", "A", 1))
        store.set_calls.clear()

        root_id, version = resolve_canonical("B", store)

        assert root_id == "A"
        assert version == 1
        assert store.set_calls == []  # single hop is already optimal

    def test_chain_resolves_to_root_and_compresses(self):
        """Verify that a duplicate chain resolves and is path-compressed."""
        store = FakeDuplicateLinkStore()
        # C -> B -> A, A is canonical root
        store.set_link(_link("B", "A", 1, match_tier="exact_hash"))
        store.set_link(
            _link("C", "B", 9, match_tier="embedding_similarity", similarity_score=0.87)
        )
        store.set_calls.clear()

        root_id, version = resolve_canonical("C", store)

        assert root_id == "A"
        assert version == 1  # version A was at, per the B->A hop
        # Path compression: C now points directly at A.
        compressed = store.get_link("C")
        assert compressed.linked_source_id == "A"
        assert compressed.linked_document_version == 1
        # Original tier/score (how C was first linked) is preserved,
        # NOT the tier of the B->A hop it walked through.
        assert compressed.match_tier == "embedding_similarity"
        assert compressed.similarity_score == 0.87
        assert store.set_calls == ["C"]  # only the queried node is rewritten

    def test_resolving_already_compressed_chain_does_not_rewrite_again(self):
        """Verify that an already-compressed chain is not rewritten."""
        store = FakeDuplicateLinkStore()
        store.set_link(_link("B", "A", 1))
        store.set_link(_link("C", "B", 9))
        resolve_canonical("C", store)  # first call compresses C -> A
        store.set_calls.clear()

        root_id, version = resolve_canonical("C", store)  # second call

        assert root_id == "A"
        assert version == 1
        assert store.set_calls == []  # already a single hop, nothing to do

    def test_longer_chain_compresses_fully_in_one_pass(self):
        """Verify that a longer duplicate chain compresses in one pass."""
        store = FakeDuplicateLinkStore()
        # D -> C -> B -> A
        store.set_link(_link("B", "A", 1))
        store.set_link(_link("C", "B", 1))
        store.set_link(_link("D", "C", 1))
        store.set_calls.clear()

        root_id, _ = resolve_canonical("D", store)

        assert root_id == "A"
        assert store.get_link("D").linked_source_id == "A"
        assert store.set_calls == ["D"]  # only D (the queried node) rewritten

    def test_midchain_node_resolution_is_independent(self):
        """Verify that resolving a node does not alter its parent link."""
        store = FakeDuplicateLinkStore()
        store.set_link(_link("B", "A", 1))
        store.set_link(_link("C", "B", 9))

        # Resolving C shouldn't touch B's own link.
        resolve_canonical("C", store)

        assert store.get_link("B").linked_source_id == "A"  # unchanged


# ---------------------------------------------------------------------------
# deduplicate — full stage entry point
# ---------------------------------------------------------------------------


class TestDeduplicate:
    def test_no_match_anywhere(self):
        """Verify that unique content is not marked as a duplicate."""
        hash_index = FakeContentHashIndex()
        link_store = FakeDuplicateLinkStore()

        result = deduplicate("new-doc", "unique content", hash_index, link_store)

        assert result == DeduplicationResult(is_duplicate=False)
        assert link_store.set_calls == []

    def test_exact_match_against_canonical_root(self):
        """Verify that an exact match links directly to its canonical root."""
        content = "duplicate content"
        content_hash = compute_content_hash(content)
        hash_index = FakeContentHashIndex({content_hash: ("original-doc", 3)})
        link_store = FakeDuplicateLinkStore()

        result = deduplicate("dep-doc", content, hash_index, link_store)

        assert result.is_duplicate is True
        assert result.canonical_source_id == "original-doc"
        assert result.canonical_version == 3
        assert result.match_tier == "exact_hash"
        assert link_store.get_link("dep-doc").linked_source_id == "original-doc"

    def test_exact_match_against_document_that_is_itself_a_duplicate(self):
        """Verify that exact matches resolve through an existing duplicate chain."""
        # dep-doc's content hash matches "target", but target is itself
        # already linked to "real-root". deduplicate() should absorb the
        # whole chain in one call, landing dep-doc directly on real-root.
        content = "syndicated content"
        content_hash = compute_content_hash(content)
        hash_index = FakeContentHashIndex({content_hash: ("target", 7)})
        link_store = FakeDuplicateLinkStore()
        link_store.set_link(
            _link(
                "target",
                "real-root",
                2,
                match_tier="embedding_similarity",
                similarity_score=0.9
                )
        )

        result = deduplicate("dep-doc", content, hash_index, link_store)

        assert result.is_duplicate is True
        assert result.canonical_source_id == "real-root"
        assert result.canonical_version == 2
        # dep-doc's own registered tier is exact_hash (that's how IT was
        # matched) — this is preserved through compression, not target's
        # embedding_similarity tier.
        assert result.match_tier == "exact_hash"
        assert link_store.get_link("dep-doc").linked_source_id == "real-root"

    def test_near_duplicate_never_fires_in_phase_2(self):
        """Verify that Tier 2 does not report duplicates during Phase 2."""
        # Even with no exact hash match, Tier 2 is a stub — no duplicate
        # is ever reported via embedding similarity in Phase 2.
        hash_index = FakeContentHashIndex()  # no exact match possible
        link_store = FakeDuplicateLinkStore()

        result = deduplicate(
            "dep-doc",
            "some near-duplicate-ish content",
            hash_index,
            link_store
            )

        assert result.is_duplicate is False
        assert result.match_tier is None
