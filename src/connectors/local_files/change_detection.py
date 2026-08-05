import hashlib
from pathlib import Path

from src.core.models import FileState


def get_mtime(path: Path) -> float:
    """Returns the mtime for a given file.

    Args:
        path (Path): path object for file.

    Returns:
        float: raw float value for mtime.
    """
    return path.stat().st_mtime


def get_size(path: Path) -> int:
    """Returns a file's size as an integer.

    Args:
        path (Path): path object for the file.

    Returns:
        int: raw size for the file.
    """
    size = path.stat().st_size
    return int(size)


def compute_file_hash(path: Path) -> str:
    """Computes a file's SHA256 hash for change detection purposes.

    Args:
        path (Path): path object for the file.

    Returns:
        str: the computed file's hash.
    """
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_change_token(
    path: Path, tracked_state: FileState | None
) -> tuple[FileState, bool]:
    """Computes the change token for a given file.

    If a tracked state is present/given:
    Uses mtime and size as a prefilter againsts the tracked state to determine
    if it's worth it to calculate the file hash.

    If a tracked state is not provided:
    The size and mtime gets computed, same as the hash and a new tracked state
    object gets created for future reference.

    Args:
        path (Path): file's path object.
        tracked_state (FileState | None): old FileState object if present

    Returns:
        tuple[FileState, bool]: Returns the freshly computed FileState object and a bool
        flag for the change status. True if file changed.
    """
    _size = get_size(path)
    _mtime = get_mtime(path)

    if tracked_state is None:
        _hash = compute_file_hash(path)
        new_state = FileState(
            source_id=str(path),
            last_hash=_hash,
            last_size=_size,
            last_mtime=_mtime,
        )
        return new_state, False  # first time seeing this file — not a "change"

    if tracked_state.last_mtime != _mtime or tracked_state.last_size != _size:
        _hash = compute_file_hash(path)
        if _hash != tracked_state.last_hash:
            new_state = FileState(
                source_id=tracked_state.source_id,
                last_hash=_hash,
                last_size=_size,
                last_mtime=_mtime,
            )
            return new_state, True  # content actually changed

        # stat differed (e.g. a touch) but content didn't — refresh stat only
        new_state = FileState(
            source_id=tracked_state.source_id,
            last_hash=tracked_state.last_hash,
            last_size=_size,
            last_mtime=_mtime,
        )
        return new_state, False

    # stat unchanged — skip hashing entirely
    return tracked_state, False
