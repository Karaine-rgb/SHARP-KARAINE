"""Tests for the odds movement visualizer. No network: the Odds API is faked
with httpx.MockTransport."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from odds_visualizer import budget, config
from odds_visualizer.oddsapi import OddsApiClient, OddsApiError, normalize_odds
from odds_visualizer.store import Store, iso
from odds_visualizer.tracker import Tracker

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


# ---- budget -----------------------------------------------------------
@pytest.mark.parametrize("mins,expected", [
    (-5, None), (0, None), (30, 20), (60, 20), (120, 45), (300, 90),
    (600, 240), (2000, 720), (5000, 1440),
])
def test_poll_interval(mins, expected):
    assert budget.poll_interval_minutes(mins) == expected


def test_is_due():
    assert budget.is_due(None, NOW, 100)
    assert not budget.is_due(NOW - timedelta(minutes=10), NOW, 30)
    assert budget.is_due(NOW - timedelta(minutes=20), NOW, 30)
    assert not budget.is_due(None, NOW, -1)


def test_cycle_end_and_allowance():
    assert budget.cycle_end(NOW, 1) == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert budget.cycle_end(NOW, 10) == datetime(2026, 11, 10, tzinfo=timezone.utc)
    # reset day 31 in a 30-day month clamps to the 30th
    assert budget.cycle_end(NOW, 31) == datetime(2026, 11, 30, tzinfo=timezone.utc)
    dec = datetime(2026, 12, 20, tzinfo=timezone.utc)
    assert budget.cycle_end(dec, 1) == datetime(2027, 1, 1, tzinfo=timezone.utc)
    # 24 days left, 485 spendable, burst 3 -> ~60.6
    a = budget.daily_allowance(510, 25, NOW, 1, 3)
    assert 60 < a < 61
    assert budget.daily_allowance(20, 25, NOW, 1, 3) == 0


def test_can_spend_rules():
    ok, _ = budget.can_spend(1, 100, 25, 0, 10, 1000, 90)
    assert ok
    ok, why = budget.can_spend(1, 25, 25, 0, 10, 1000, 90)
    assert not ok and "reserve" in why
    ok, why = budget.can_spend(1, 100, 25, 10, 10, 1000, 90)
    assert not ok and "daily" in why
    ok, why = budget.can_spend(1, 100, 25, 10, 10, 30, 90)
    assert ok and "priority" in why
    # manual may use the reserve but never go below zero
    assert budget.can_spend(1, 10, 25, 99, 0, 1000, 90, manual=True)[0]
    assert not budget.can_spend(2, 1, 25, 0, 0, 1000, 90, manual=True)[0]


def test_estimated_cost():
    assert config.estimated_cost(1, 10) == 1
    assert config.estimated_cost(1, 11) == 2
    assert config.estimated_cost(2, 3) == 2


# ---- normalization ----------------------------------------------------
ODDS_PAYLOAD = [{
    "id": "ev1", "sport_key": "soccer_epl", "sport_title": "EPL",
    "commence_time": iso(NOW + timedelta(hours=3)), "home_team": "A", "away_team": "B",
    "bookmakers": [
        {"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-11-07T11:59:00Z",
         "markets": [{"key": "h2h", "last_update": "2026-11-07T11:59:00Z", "outcomes": [
             {"name": "A", "price": 2.1}, {"name": "B", "price": 3.5}, {"name": "Draw", "price": 3.3}]}]},
        {"key": "betfair_ex_uk", "title": "Betfair", "markets": [{"key": "h2h", "outcomes": [
            {"name": "A", "price": 2.14}, {"name": "B", "price": None}]}]},
    ],
}]


def test_normalize_odds():
    rows = normalize_odds(ODDS_PAYLOAD, "2026-11-07T12:00:00Z")
    assert len(rows) == 4  # None price skipped
    assert {r["bookmaker"] for r in rows} == {"pinnacle", "betfair_ex_uk"}
    assert rows[0]["price"] == 2.1 and rows[0]["fetched_at"] == "2026-11-07T12:00:00Z"
    assert normalize_odds([], "x") == []


# ---- tracker with a fake API -----------------------------------------
def make_tracker(handler, now=NOW):
    store = Store(":memory:")
    client = OddsApiClient(api_key="k", base="https://api.test/v4", transport=httpx.MockTransport(handler))
    return Tracker(store, client, now_fn=lambda: now), store


def headers(remaining, last):
    return {"x-requests-remaining": str(remaining), "x-requests-used": str(500 - remaining),
            "x-requests-last": str(last)}


@pytest.mark.asyncio
async def test_poll_stores_snapshots_and_reads_quota_headers():
    seen = {}

    def handler(req: httpx.Request):
        seen["params"] = dict(req.url.params)
        return httpx.Response(200, json=ODDS_PAYLOAD, headers=headers(480, 1))

    tracker, store = make_tracker(handler)
    store.upsert_events("soccer_epl", [{"id": "ev1", "home_team": "A", "away_team": "B",
                                        "commence_time": iso(NOW + timedelta(hours=3))}])
    store.set_tracked("ev1", True)

    r = await tracker.poll_sport("soccer_epl")
    assert r["polled"] and r["prices"] == 4
    assert seen["params"]["eventIds"] == "ev1"
    assert seen["params"]["markets"] == ",".join(config.MARKETS)
    assert seen["params"]["oddsFormat"] == "decimal"
    assert tracker.remaining() == 480
    assert len(store.snapshots("ev1", "h2h")) == 4
    assert store.calls()[0]["cost"] == 1


@pytest.mark.asyncio
async def test_tick_respects_schedule():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json=ODDS_PAYLOAD, headers=headers(400, 1))

    clock = {"now": NOW}
    store = Store(":memory:")
    client = OddsApiClient(api_key="k", base="https://api.test/v4", transport=httpx.MockTransport(handler))
    tracker = Tracker(store, client, now_fn=lambda: clock["now"])
    store.upsert_events("soccer_epl", [{"id": "ev1", "home_team": "A", "away_team": "B",
                                        "commence_time": iso(NOW + timedelta(hours=3))}])
    store.set_tracked("ev1", True)

    await tracker.tick()            # first poll
    await tracker.tick()            # not due again yet
    assert len(calls) == 1
    clock["now"] = NOW + timedelta(minutes=91)  # 3h out -> every 90 min
    await tracker.tick()
    assert len(calls) == 2
    clock["now"] = NOW + timedelta(hours=4)     # kicked off -> stop
    await tracker.tick()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_reserve_blocks_automatic_poll():
    def handler(req):
        return httpx.Response(200, json=ODDS_PAYLOAD, headers=headers(config.RESERVE_CREDITS, 1))

    tracker, store = make_tracker(handler)
    store.upsert_events("soccer_epl", [{"id": "ev1", "home_team": "A", "away_team": "B",
                                        "commence_time": iso(NOW + timedelta(hours=3))}])
    store.set_tracked("ev1", True)
    await tracker.poll_sport("soccer_epl", manual=True)   # sets remaining == reserve
    r = await tracker.poll_sport("soccer_epl")
    assert not r["polled"] and "reserve" in r["reason"]


@pytest.mark.asyncio
async def test_api_error_is_logged_and_cooled_down():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(401, json={"message": "bad key"})

    tracker, store = make_tracker(handler)
    store.upsert_events("soccer_epl", [{"id": "ev1", "home_team": "A", "away_team": "B",
                                        "commence_time": iso(NOW + timedelta(hours=3))}])
    store.set_tracked("ev1", True)
    res = await tracker.tick()
    assert not res[0]["polled"] and "401" in res[0]["reason"]
    await tracker.tick()  # inside cooldown -> no second call
    assert len(calls) == 1
    assert store.calls()[0]["ok"] == 0
    with pytest.raises(OddsApiError):
        await tracker.poll_sport("soccer_epl", manual=True)


@pytest.mark.asyncio
async def test_refresh_fixtures():
    def handler(req):
        assert req.url.path.endswith("/sports/soccer_epl/events")
        return httpx.Response(200, headers=headers(500, 0), json=[
            {"id": "e1", "sport_title": "EPL", "home_team": "A", "away_team": "B",
             "commence_time": iso(NOW + timedelta(days=1))}])

    tracker, store = make_tracker(handler)
    evs = await tracker.refresh_fixtures("soccer_epl")
    assert [e["id"] for e in evs] == ["e1"] and evs[0]["tracked"] == 0
    assert store.calls()[0]["cost"] == 0


def test_demo_seed_and_series_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from odds_visualizer import server, demo

    store = Store(":memory:")
    demo.seed(store, datetime.now(timezone.utc))
    monkeypatch.setattr(server, "tracker", Tracker(store, None))
    c = TestClient(server.app)
    assert c.get("/api/status").json()["demo"] is True
    tracked = c.get("/api/events?tracked=true").json()
    assert len(tracked) == 3
    s = c.get(f"/api/events/{tracked[0]['id']}/series").json()
    assert s["market"] == "h2h"
    assert s["outcomes"][1] == "Draw"
    assert len(s["bookmakers"]) == len(config.BOOKMAKERS)
    assert c.post("/api/poll/soccer_epl").status_code == 400  # demo mode refuses
