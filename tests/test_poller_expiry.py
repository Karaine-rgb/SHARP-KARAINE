"""Strict no-data-after-kickoff cutoff. Uses a fake db module (monkeypatched)
rather than a real Postgres connection, so this runs without network/DB.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.poller import MatchState, Poller
from app.config import settings


class FakeDB:
    def __init__(self):
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))

    async def fetch(self, query, *args):
        return []


class EmptyClient:
    async def get_matchup_markets(self, mid):
        return []


@pytest.mark.asyncio
async def test_tick_auto_unmonitors_match_once_kickoff_has_passed(monkeypatch):
    fake_db = FakeDB()
    row = {
        "id": 1,
        "pinnacle_matchup_id": 999,
        "home_team": "A",
        "away_team": "B",
        "start_time": datetime.now(timezone.utc) - timedelta(seconds=1),
    }

    async def fake_fetch(query, *args):
        return [row]

    fake_db.fetch = fake_fetch
    monkeypatch.setattr("app.poller.db", fake_db)

    from app.ws import manager

    async def fake_broadcast(msg):
        pass

    monkeypatch.setattr(manager, "broadcast", fake_broadcast)

    p = Poller()
    p._client = EmptyClient()
    await p._tick()

    assert any("is_monitored = false" in q for q, _ in fake_db.executed)
    assert 1 not in p._states  # never scheduled for polling


@pytest.mark.asyncio
async def test_tick_still_polls_a_match_before_kickoff(monkeypatch):
    fake_db = FakeDB()
    row = {
        "id": 2,
        "pinnacle_matchup_id": 888,
        "home_team": "A",
        "away_team": "B",
        "start_time": datetime.now(timezone.utc) + timedelta(hours=2),
    }

    async def fake_fetch(query, *args):
        return [row]

    fake_db.fetch = fake_fetch
    monkeypatch.setattr("app.poller.db", fake_db)

    from app.ws import manager

    async def fake_broadcast(msg):
        pass

    monkeypatch.setattr(manager, "broadcast", fake_broadcast)

    async def fake_ingest(matchup_id, raw_markets):
        return []

    monkeypatch.setattr("app.poller.ingest.ingest_matchup_markets", fake_ingest)

    async def fake_compute_and_store_score(matchup_id, kickoff):
        return {"tier": "insufficient_data", "sharp_side": None, "total_score": 0.0}

    monkeypatch.setattr("app.poller.signals.compute_and_store_score", fake_compute_and_store_score)

    async def fake_maybe_alert(*a, **kw):
        pass

    monkeypatch.setattr("app.poller.telegram.maybe_alert_tier_change", fake_maybe_alert)

    p = Poller()
    p._client = EmptyClient()
    await p._tick()

    assert not any("is_monitored = false" in q for q, _ in fake_db.executed)
    assert 2 in p._states  # scheduled for polling, not skipped


@pytest.mark.asyncio
async def test_poll_one_discards_data_when_kickoff_passes_mid_poll(monkeypatch):
    """The in-flight race: _tick() accepted this match before kickoff, but
    time has moved on by the time the (simulated) network call returns -
    the strict rule still applies, so the cycle's data must be discarded
    rather than ingested and stored.
    """
    fake_db = FakeDB()
    monkeypatch.setattr("app.poller.db", fake_db)

    from app.ws import manager

    async def fake_broadcast(msg):
        pass

    monkeypatch.setattr(manager, "broadcast", fake_broadcast)

    ingest_called = False

    async def fake_ingest(matchup_id, raw_markets):
        nonlocal ingest_called
        ingest_called = True
        return []

    monkeypatch.setattr("app.poller.ingest.ingest_matchup_markets", fake_ingest)

    p = Poller()
    p._client = EmptyClient()
    row = {
        "id": 3,
        "pinnacle_matchup_id": 777,
        # Already past kickoff by the time _poll_one actually checks -
        # simulates kickoff landing while the request was in flight.
        "start_time": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    state = MatchState(settings.poll_base_interval)
    await p._poll_one(row, state, datetime.now(timezone.utc) - timedelta(seconds=5))

    assert any("is_monitored = false" in q for q, _ in fake_db.executed)
    assert not ingest_called


@pytest.mark.asyncio
async def test_poll_one_does_not_unmonitor_empty_markets_before_kickoff(monkeypatch):
    """A future match legitimately has no markets open yet in edge cases -
    that alone is never treated as a settled/kickoff signal.
    """
    fake_db = FakeDB()
    monkeypatch.setattr("app.poller.db", fake_db)

    from app.ws import manager

    async def fake_broadcast(msg):
        pass

    monkeypatch.setattr(manager, "broadcast", fake_broadcast)

    async def fake_ingest(matchup_id, raw_markets):
        return []

    monkeypatch.setattr("app.poller.ingest.ingest_matchup_markets", fake_ingest)

    async def fake_compute_and_store_score(matchup_id, kickoff):
        return {"tier": "insufficient_data", "sharp_side": None, "total_score": 0.0}

    monkeypatch.setattr("app.poller.signals.compute_and_store_score", fake_compute_and_store_score)

    async def fake_maybe_alert(*a, **kw):
        pass

    monkeypatch.setattr("app.poller.telegram.maybe_alert_tier_change", fake_maybe_alert)

    p = Poller()
    p._client = EmptyClient()
    row = {
        "id": 4,
        "pinnacle_matchup_id": 666,
        "home_team": "A",
        "away_team": "B",
        "start_time": datetime.now(timezone.utc) + timedelta(hours=2),
    }
    state = MatchState(settings.poll_base_interval)
    await p._poll_one(row, state, datetime.now(timezone.utc))

    assert not any("is_monitored = false" in q for q, _ in fake_db.executed)
