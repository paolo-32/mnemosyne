"""On-disk attachment storage.

content-addressed, relative to the Raw Store's own SQLite file directory.

Convention (proposed default from the orchestration plan, §3):
    <raw_store_dir>/attachments/<sha256[:2]>/<sha256>

Only a path/hash reference is stored in the documents table itself (via
Attachment.hash) -- this module is the one place that knows how to turn
that hash into an actual filesystem location, and the one place that
writes/reads the binary content.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class AttachmentStore:
    def __init__(self, raw_store_dir: Path) -> None:
        """Initialize the attachment store relative to the Raw Store directory."""
        self._root = Path(raw_store_dir) / "attachments"
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for_hash(self, sha256_hex: str) -> Path:
        """Return the filesystem path for an attachment hash."""
        return self._root / sha256_hex[:2] / sha256_hex

    def put(self, content: bytes) -> str:
        """Store content by its SHA-256 hash and return the hash."""
        digest = hashlib.sha256(content).hexdigest()
        path = self._path_for_hash(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return digest

    def get(self, sha256_hex: str) -> bytes:
        """Return attachment content for a SHA-256 hash."""
        path = self._path_for_hash(sha256_hex)
        if not path.exists():
            raise FileNotFoundError(f"No attachment content for hash {sha256_hex}")
        return path.read_bytes()

    def exists(self, sha256_hex: str) -> bool:
        """Return whether attachment content exists for a hash."""
        return self._path_for_hash(sha256_hex).exists()
