import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class TikaConfig(BaseModel):
    endpoint: str = "http://localhost:9998"


class OllamaConfig(BaseModel):
    endpoint: str = "http://localhost:11434"
    embedding_model: str = "embeddinggemma"
    llm_model: str = "gemma4:e4b"


class RawStoreConfig(BaseModel):
    db_path: str = "./data/raw_store.sqlite"


class ConnectorStateStoreConfig(BaseModel):
    db_path: str = "./data/connector_state.sqlite"


class QdrantConfig(BaseModel):
    endpoint: str = "http://localhost:6333"


class Settings(BaseModel):
    tika: TikaConfig = TikaConfig()
    ollama: OllamaConfig = OllamaConfig()
    raw_store: RawStoreConfig = RawStoreConfig()
    connector_state_store: ConnectorStateStoreConfig = ConnectorStateStoreConfig()
    qdrant: QdrantConfig = QdrantConfig()

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        """Loads the config.yaml file.

        Args:
            path (Path | None, optional): Path of the config file. Defaults to None.

        Returns:
            Settings: Settings object.
        """
        data = {}
        if path and path.exists():
            data = yaml.safe_load(path.read_text()) or {}

        settings = cls.model_validate(data)
        _apply_env_overrides(settings)
        return settings


def _apply_env_overrides(settings: Settings) -> None:
    if endpoint := os.environ.get("MNEMOSYNE_TIKA_ENDPOINT"):
        settings.tika.endpoint = endpoint
    if endpoint := os.environ.get("MNEMOSYNE_OLLAMA_ENDPOINT"):
        settings.ollama.endpoint = endpoint
    if db_path := os.environ.get("MNEMOSYNE_RAW_STORE_DB"):
        settings.raw_store.db_path = db_path
    if endpoint := os.environ.get("MNEMOSYNE_QDRANT_ENDPOINT"):
        settings.qdrant.endpoint = endpoint
