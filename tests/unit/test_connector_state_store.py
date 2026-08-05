from datetime import UTC, datetime, timedelta

import pytest

from src.stores.connector_state_store.repository import ConnectorStateStoreRepository


@pytest.fixture()
def repo(tmp_path):
    repository = ConnectorStateStoreRepository(tmp_path / "connector_state.sqlite")
    yield repository
    repository.close()


def test_cursor_roundtrip(repo):
    assert repo.get_cursor("scraper_x") is None

    now = datetime.now(UTC)
    repo.set_cursor("scraper_x", "page=3", now)

    cursor = repo.get_cursor("scraper_x")
    assert cursor.cursor == "page=3"
    assert cursor.connector_id == "scraper_x"


def test_cursor_overwritten_on_each_call(repo):
    t1 = datetime.now(UTC)
    repo.set_cursor("scraper_x", "page=1", t1)
    t2 = t1 + timedelta(seconds=30)
    repo.set_cursor("scraper_x", "page=2", t2)

    assert repo.get_cursor("scraper_x").cursor == "page=2"


def test_heartbeat_not_stuck_when_recent(repo):
    repo.declare_heartbeat_expectations("watcher", expected_interval_seconds=300, grace_period_seconds=60)
    now = datetime.now(UTC)
    repo.report_heartbeat("watcher", now)

    assert repo.is_stuck("watcher", now + timedelta(seconds=100)) is False


def test_heartbeat_stuck_when_overdue(repo):
    repo.declare_heartbeat_expectations("watcher", expected_interval_seconds=300, grace_period_seconds=60)
    now = datetime.now(UTC)
    repo.report_heartbeat("watcher", now)

    assert repo.is_stuck("watcher", now + timedelta(seconds=1000)) is True


def test_discrete_connector_never_flagged_stuck(repo):
    """No heartbeat expectations declared at all -- discrete-mode connectors
    don't need this field (§18.2.2).
    """
    assert repo.is_stuck("one_shot_importer", datetime.now(UTC)) is False
