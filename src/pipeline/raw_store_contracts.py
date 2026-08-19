"""Pipeline-side contracts for what pipeline stages need from the Raw Store.

Distinct in kind from `stores/graph_store/adapter.py`: that Protocol exists
because multiple Graph Store implementations are anticipated (LadybugDB,
Neo4j); an implementer-side contract living neutrally above its sibling
implementations. Here there is exactly one Raw Store implementation
(SQLite, deliberately the conservative/settled choice, as per the tech-stack),
and no swap is anticipated.

These Protocols exist instead for testability: per the paradigm table,
domain logic like dedup comparison should be testable against in-memory
fakes without a live store. `RawStoreRepository` never needs to import or
inherit from these, python's structural typing means it satisfies them
just by having matching method signatures (same reasoning already used
for the `Extractor` Protocol in `tika_extractor.py`).
"""


from typing import Protocol

from core.models import DuplicateLink


# ---------------------------------------------------------------------------
# Store-facing Protocols — kept minimal and store-agnostic.
# ---------------------------------------------------------------------------

class ContentHashIndex(Protocol):
    """Backs Tier 1 - the cheap exact hash filter (6.3)."""

    def lookup(self, content_hash: str) -> tuple[str, int] | None:
        """Return (source_id, version) of the current document.

        Content must match exactly, otherwise returns None if no
        match exists.

        Must only consider *current* (non-superseeded) documents;
        a duplicate match against a superseeded version would link
        against content that's no longer the authoritative version
        of that source_id.
        """
        ...

class DuplicateLinkStore(Protocol):
    """Backs the union-find parent-pointer table ('duplicate_links')."""

    def get_link(self, source_id: str) -> DuplicateLink | None:
        """Return the duplicate link for a source ID, if one exists."""
        ...

    def set_link(self, link: DuplicateLink) -> None:
        """Store or update a duplicate link."""
        ...
