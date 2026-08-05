from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from src.core.models import ConnectorItemResult


@runtime_checkable
class Connector(Protocol):
    def run(self) -> Iterator[ConnectorItemResult]:
        ...

