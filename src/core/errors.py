"""Domain-level exceptions.

No I/O-specific exceptions here -- those belong
in the store/connector modules that raise them.
"""


class MnemosyneError(Exception):
    """Base class for all Mnemosyne domain errors."""


class DocumentNotFoundError(MnemosyneError):
    """Raised when a lookup by document id or source_id finds nothing."""


class NoOpIngestionError(MnemosyneError):
    """Raised (or caught internally) when an incoming change_token matches
    the last-known token for a source_id -- unchanged content, no new
    version should be created (§16.2, §18.3).
    """


class UnknownConnectorError(MnemosyneError):
    """Raised when connector-state operations reference a connector_id with
    no prior registered state.
    """
