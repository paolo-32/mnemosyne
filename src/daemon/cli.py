# daemon/cli.py
from pathlib import Path

import typer

from src.config.settings import Settings
from src.connectors.local_files.connector import LocalFilesConnector
from src.connectors.local_files.tika_extractor import TikaExtractor
from src.core.enums import ItemStatus
from src.core.errors import NoOpIngestionError
from src.stores.connector_state_store.repository import ConnectorStateStoreRepository
from src.stores.raw_store.repository import RawStoreRepository

app = typer.Typer()


@app.command()
def ingest_local(
    folder: Path = typer.Argument(..., help="Root directory to ingest."),
    config_path: Path = typer.Option(
        Path("config/mnemosyne.yaml"), help="Path to config YAML."
    ),
) -> None:
    """Ingest all files under FOLDER into the Raw Store (discrete mode)."""
    settings = Settings.load(config_path)

    tika_extractor = TikaExtractor(endpoint=settings.tika.endpoint)
    connector_state_repo = ConnectorStateStoreRepository(
        settings.connector_state_store.db_path
    )
    raw_store_repo = RawStoreRepository(settings.raw_store.db_path)

    connector = LocalFilesConnector(
        root_path=folder,
        tika_extractor=tika_extractor,
        connector_state_repo=connector_state_repo,
    )

    counts = {status: 0 for status in ItemStatus}

    for result in connector.run():
        if result.status == ItemStatus.SUCCESS:
            try:
                raw_store_repo.ingest(result.document)
                counts[ItemStatus.SUCCESS] += 1
            except NoOpIngestionError:
                counts[ItemStatus.UNCHANGED] += 1
        elif result.status in (ItemStatus.FAILED_TRANSIENT, ItemStatus.FAILED_PERMANENT):
            counts[result.status] += 1
            typer.echo(f"[{result.status.value}] {result.source_id}: {result.error}")
        else:
            counts[result.status] += 1

    typer.echo(
        f"Done. success={counts[ItemStatus.SUCCESS]} "
        f"unchanged={counts[ItemStatus.UNCHANGED]} "
        f"failed_transient={counts[ItemStatus.FAILED_TRANSIENT]} "
        f"failed_permanent={counts[ItemStatus.FAILED_PERMANENT]}"
    )

    connector_state_repo.close()
    raw_store_repo.close()


if __name__ == "__main__":
    app()