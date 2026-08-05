from collections.abc import Iterator
from pathlib import Path

from .change_detection import compute_change_token
from .format_extractors import get_extractor
from .tika_extractor import Extractor
from src.core.enums import IngestionMode, ItemStatus
from src.core.models import CanonicalDocument, ConnectorItemResult, Provenance
from src.stores.connector_state_store.repository import (
    ConnectorStateStoreRepository,
)


class LocalFilesConnector:
    """Connector for ingesting documents from a local filesystem."""

    def __init__(
        self,
        root_path: Path,
        tika_extractor: Extractor,
        connector_state_repo: ConnectorStateStoreRepository,
    ) -> None:
        """Initialize the local files connector.

        Args:
            root_path: Root directory to scan for files.
            tika_extractor: Extractor used for unsupported document formats.
            connector_state_repo: Repository used to track file state.
        """
        self.root_path = root_path
        self.tika_extractor = tika_extractor
        self.connector_state_repo = connector_state_repo

    def run(self) -> Iterator[ConnectorItemResult]:
        """Scan files and yield ingestion results.

        Returns:
            An iterator containing the result of processing each file.
        """
        for path in self.root_path.rglob("*"):
            if not path.is_file():
                continue

            source_id = str(path.resolve())
            tracked_state = self.connector_state_repo.get_file_state(source_id)
            new_state, changed = compute_change_token(path, tracked_state)

            if tracked_state is not None and not changed:
                yield ConnectorItemResult(
                    source_id=source_id,
                    status=ItemStatus.UNCHANGED,
                )
                continue

            extractor = get_extractor(path, self.tika_extractor)
            if extractor is None:
                yield ConnectorItemResult(
                    source_id=source_id,
                    status=ItemStatus.FAILED_PERMANENT,
                    error=f"Unsupported file extension: {path.suffix}",
                )
                continue

            try:
                extracted = extractor(path)
            except Exception as exc:
                status, error = self._map_extraction_error(exc)
                yield ConnectorItemResult(
                    source_id=source_id,
                    status=status,
                    error=error,
                )
                continue

            document = CanonicalDocument(
                source_id=source_id,
                source_type="local_files",
                change_token=new_state.last_hash,
                hash=new_state.last_hash,
                raw_content=extracted.raw_content,
                metadata={
                    **extracted.metadata,
                    "format": path.suffix.lstrip("."),
                },
                provenance=Provenance(
                    connector_id="local_files",
                    ingestion_mode=IngestionMode.DISCRETE,
                    cursor_at_ingestion=None,
                ),
            )

            self.connector_state_repo.set_file_state(new_state)

            yield ConnectorItemResult(
                source_id=source_id,
                status=ItemStatus.SUCCESS,
                document=document,
            )

    def _map_extraction_error(
        self,
        exc: Exception,
    ) -> tuple[ItemStatus, str]:
        """Map extraction exceptions to ingestion statuses.

        Args:
            exc: Exception raised during content extraction.

        Returns:
            The corresponding item status and error message.
        """
        # TODO: narrow this to actual Tika connectivity exception types
        # once TikaExtractor's failure modes are confirmed
        if "tika" in str(exc).lower() or "connection" in str(exc).lower():
            return ItemStatus.FAILED_TRANSIENT, str(exc)

        return ItemStatus.FAILED_PERMANENT, str(exc)
