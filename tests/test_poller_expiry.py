"""Auto-expiry logic for finished/stale matches, per the config's
auto_expire_hours_after_kickoff. Uses a fake db module (monkeypatched)
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
async def test_tick_auto_unmonitors_match_past_expiry_window(monkeypatch):
    fake_db = FakeDB()
    old_kickoff = datetime.now(timezone.utc) - timedelta(
        hours=settings.auto_expire_hours_after_kickoff + 1
    )
    row = {
        "id": 1,
        "pinnacle_matchup_id": 999,
        "home_team": "A",
        "away_team": "B",
        "start_time": old_kickoff,
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
async def test_poll_one_auto_unmonitors_when_pinnacle_returns_no_markets_post_kickoff(monkeypatch):
    fake_db = FakeDB()
    monkeypatch.setattr("app.poller.db", fake_db)

    from app.ws import manager

    async def fake_broadcast(msg):
        pass

    monkeypatch.setattr(manager, "broadcast", fake_broadcast)

    p = Poller()
    p._client = EmptyClient()
    row = {
        "id": 2,
        "pinnacle_matchup_id": 888,
        "home_team": "A",
        "away_team": "B",
        "start_time": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    state = MatchState(settings.poll_base_interval)
    await p._poll_one(row, state, datetime.now(timezone.utc))

    assert any("is_monitored = false" in q for q, _ in fake_db.executed)


@pytest.mark.asyncio
async def test_poll_one_does_not_unmonitor_empty_markets_before_kickoff(monkeypatch):
    """A future match legitimately has no markets open yet in edge cases -
    only treat 'no markets' as a settled signal once kickoff has passed.
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
        "id": 3,
        "pinnacle_matchup_id": 777,
        "home_team": "A",
        "away_team": "B",
        "start_time": datetime.now(timezone.utc) + timedelta(hours=2),
    }
    state = MatchState(settings.poll_base_interval)
    await p._poll_one(row, state, datetime.now(timezone.utc))

    assert not any("is_monitored = false" in q for q, _ in fake_db.executed)
