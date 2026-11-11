import pytest

from app.poller import Poller
from app.storage_guard import StorageGuard, describe_usage


def test_describe_usage_levels_and_free_space():
    d = lambda used: describe_usage(used, 1000, 80, 90, 95)
    assert d(500)["level"] == "ok"
    assert d(800)["level"] == "warning"
    assert d(900)["level"] == "critical"
    assert d(950)["level"] == "paused"
    u = d(700)
    assert u["free_bytes"] == 300 and u["used_pct"] == 70.0
    assert u["pause_bytes"] == 950 and u["usable_bytes"] == 250
    assert d(1200)["free_bytes"] == 0


class Sizer:
    def __init__(self, size):
        self.size = size
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if isinstance(self.size, Exception):
            raise self.size
        return self.size


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(sizer, clock=None):
    return StorageGuard(1000, 80, 90, 95, size_fn=sizer, clock=clock or Clock())


@pytest.mark.asyncio
async def test_pauses_at_threshold_and_resumes_only_below_the_margin():
    s, c = Sizer(960), Clock()
    g = make(s, c)
    assert await g.collection_blocked() is True
    for size, expected in ((940, True), (931, True), (929, False)):  # resume below 95 - 2 = 93%
        s.size = size
        c.t += 61
        assert await g.collection_blocked() is expected, size
    s.size = 960
    c.t += 61
    assert await g.collection_blocked() is True  # pauses again


@pytest.mark.asyncio
async def test_usage_is_cached_between_checks():
    s, c = Sizer(100), Clock()
    g = make(s, c)
    await g.usage()
    await g.usage()
    assert s.calls == 1
    c.t += 61
    await g.usage()
    assert s.calls == 2
    await g.usage(force=True)
    assert s.calls == 3


@pytest.mark.asyncio
async def test_guard_fails_open_when_size_cannot_be_read():
    g = make(Sizer(RuntimeError("db down")))
    assert await g.collection_blocked() is False


class FakeDB:
    def __init__(self, rows):
        self.rows, self.executed = rows, []

    async def fetch(self, query, *args):
        return self.rows

    async def execute(self, query, *args):
        self.executed.append(query)


@pytest.mark.asyncio
async def test_poller_skips_polling_while_paused_but_still_unmonitors_after_kickoff(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.ws import manager

    now = datetime.now(timezone.utc)
    rows = [
        {"id": 1, "pinnacle_matchup_id": 1, "home_team": "A", "away_team": "B", "start_time": now + timedelta(hours=2)},
        {"id": 2, "pinnacle_matchup_id": 2, "home_team": "C", "away_team": "D", "start_time": now - timedelta(seconds=1)},
    ]
    fake = FakeDB(rows)
    monkeypatch.setattr("app.poller.db", fake)
    sent = []

    async def fake_broadcast(msg):
        sent.append(msg)

    monkeypatch.setattr(manager, "broadcast", fake_broadcast)
    polled = []

    async def fake_poll_one(self, row, state, now):
        polled.append(row["id"])

    monkeypatch.setattr(Poller, "_poll_one", fake_poll_one)
    s = Sizer(980)
    p = Poller(storage_guard=make(s))
    p.force_poll(1)  # a forced poll must wait out the pause, not be lost
    await p._tick()
    assert polled == []  # paused: no new snapshots
    assert any("is_monitored = false" in q for q in fake.executed)  # kickoff cleanup still runs
    assert [m["type"] for m in sent].count("storage_paused") == 1
    await p._tick()
    assert [m["type"] for m in sent].count("storage_paused") == 1  # announced once, not every tick
    s.size = 500
    p._guard._cached_at = -1000  # expire the cache
    await p._tick()
    assert polled == [1]
    assert "storage_resumed" in [m["type"] for m in sent]
