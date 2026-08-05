"""Tests for connectors/local_files/change_detection.py.

Covers the mtime/size two-tier pre-filter (§19.3): cheap stat comparison,
falling back to content hashing only when stat looks like it might have
changed, and the "touch with no content change" edge case.
"""

import hashlib

import pytest

from src.connectors.local_files.change_detection import (
    compute_change_token,
    compute_file_hash,
    get_mtime,
    get_size,
)
from src.core.models import FileState


@pytest.fixture
def sample_file(tmp_path):
    """Create a sample text file for change-detection tests."""
    path = tmp_path / "sample.txt"
    path.write_text("hello world")
    return path


# -- primitives --------------------------------------------------------


def test_get_size_matches_stat(sample_file):
    """Verify that get_size() returns the file's size from stat()."""
    assert get_size(sample_file) == sample_file.stat().st_size


def test_get_mtime_matches_stat(sample_file):
    """Verify that get_mtime() returns the file's modification time."""
    assert get_mtime(sample_file) == sample_file.stat().st_mtime


def test_compute_file_hash_matches_manual_sha256(sample_file):
    """Verify that compute_file_hash() matches a manual SHA-256 digest."""
    expected = hashlib.sha256(sample_file.read_bytes()).hexdigest()
    assert compute_file_hash(sample_file) == expected


def test_compute_file_hash_changes_with_content(sample_file):
    """Verify that changing file contents changes the computed hash."""
    original = compute_file_hash(sample_file)
    sample_file.write_text("different content")
    assert compute_file_hash(sample_file) != original


# -- compute_change_token: no tracked state -----------------------------


def test_no_tracked_state_returns_new_filestate(sample_file):
    """Verify that a new FileState is returned when no state is tracked."""
    new_state, changed = compute_change_token(sample_file, None)

    assert isinstance(new_state, FileState)
    assert new_state.source_id == str(sample_file)
    assert new_state.last_hash == compute_file_hash(sample_file)
    assert new_state.last_size == sample_file.stat().st_size
    assert new_state.last_mtime == sample_file.stat().st_mtime
    # first sighting is not reported as a "change" by this function --
    # the caller already knows tracked_state was None and can treat
    # this branch as "new" on its own.
    assert changed is False


# -- compute_change_token: stat unchanged --------------------------------


def test_stat_unchanged_skips_hashing_entirely(sample_file, monkeypatch):
    """Verify that unchanged file metadata avoids recomputing the hash."""
    stat = sample_file.stat()
    tracked_state = FileState(
        source_id=str(sample_file),
        last_mtime=stat.st_mtime,
        last_size=stat.st_size,
        last_hash="prehashed-value-should-not-be-recomputed",
    )

    def _boom(*args, **kwargs):
        raise AssertionError("compute_file_hash should not be called")

    monkeypatch.setattr(
        "src.connectors.local_files.change_detection.compute_file_hash", _boom
    )

    new_state, changed = compute_change_token(sample_file, tracked_state)

    assert changed is False
    assert new_state is tracked_state  # returned verbatim, no re-hash


# -- compute_change_token: stat differs, content actually changed --------


def test_stat_differs_and_content_changed_reports_change(sample_file):
    """Verify that modified content is detected after a metadata change."""
    stat = sample_file.stat()
    stale_state = FileState(
        source_id=str(sample_file),
        last_mtime=stat.st_mtime - 100,  # force mtime mismatch
        last_size=stat.st_size,
        last_hash="stale-hash-that-will-not-match",
    )

    new_state, changed = compute_change_token(sample_file, stale_state)

    assert changed is True
    assert new_state.last_hash == compute_file_hash(sample_file)
    assert new_state.last_mtime == stat.st_mtime
    assert new_state.last_size == stat.st_size
    assert new_state.source_id == stale_state.source_id


def test_content_change_with_same_size_still_detected(sample_file):
    """Content edited such that size happens to stay the same, but mtime differs.

    the 'or' condition must still trigger a hash comparison.
    """
    original_size = sample_file.stat().st_size
    stale_state = FileState(
        source_id=str(sample_file),
        last_mtime=sample_file.stat().st_mtime - 100,
        last_size=original_size,
        last_hash="stale-hash",
    )

    # overwrite with different content of the exact same byte length
    replacement = "x" * original_size
    sample_file.write_text(replacement)
    assert sample_file.stat().st_size == original_size

    new_state, changed = compute_change_token(sample_file, stale_state)

    assert changed is True
    assert new_state.last_hash == compute_file_hash(sample_file)


# -- compute_change_token: stat differs, content unchanged (touch case) --


def test_touch_with_no_content_change_refreshes_stat_only(sample_file):
    """Verify that touching a file refreshes metadata without reporting a change."""
    original_hash = compute_file_hash(sample_file)
    stat = sample_file.stat()

    stale_state = FileState(
        source_id=str(sample_file),
        last_mtime=stat.st_mtime - 100,  # simulate a touch: mtime moved
        last_size=stat.st_size,
        last_hash=original_hash,
    )

    new_state, changed = compute_change_token(sample_file, stale_state)

    assert changed is False
    # hash preserved from tracked state (content genuinely unchanged)
    assert new_state.last_hash == original_hash
    # but stat fields refreshed to current values
    assert new_state.last_mtime == stat.st_mtime
    assert new_state.last_size == stat.st_size
