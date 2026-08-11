"""Domain-level exceptions.

No I/O-specific exceptions here -- those belong
in the store/connector modules that raise them.
"""


class MnemosyneError(Exception):
    """Base class for all Mnemosyne domain errors."""


class DocumentNotFoundError(MnemosyneError):
    """Raised when a lookup by document id or source_id finds nothing."""


class NoOpIngestionError(MnemosyneError):
    """Raised when an incoming change token matches the latest known token.

    Unchanged content does not create a new version (§16.2, §18.3).
    """


class UnknownConnectorError(MnemosyneError):
    """Raised when connector state is requested for an unknown connector."""
