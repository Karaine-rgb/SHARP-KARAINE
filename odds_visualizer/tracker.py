"""Ties the API client, budget rules and storage together, and runs the
background polling loop."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import budget, config
from .oddsapi import OddsApiClient, OddsApiError, normalize_odds
from .store import Store, iso, parse

log = logging.getLogger("odds_visualizer")

FAILURE_COOLDOWN = timedelta(minutes=15)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tracker:
    def __init__(self, store: Store, client: OddsApiClient | None,
                 now_fn: Callable[[], datetime] = utcnow):
        self.store = store
        self.client = client
        self.now = now_fn
        self._failed_at: dict[str, datetime] = {}
        self._task: asyncio.Task | None = None
        self.last_skip: dict[str, str] = {}  # sport -> why the last due poll was skipped

    # ---- budget --------------------------------------------------------
    def remaining(self) -> int:
        known = self.store.last_known_remaining()
        if known is not None:
            return known
        # No call made yet: assume a full month minus anything logged.
        return config.MONTHLY_CREDITS - self.store.spent_since(self.now() - timedelta(days=31))

    def budget_status(self) -> dict:
        now = self.now()
        remaining = self.remaining()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        allowance = budget.daily_allowance(remaining, config.RESERVE_CREDITS, now,
                                           config.RESET_DAY, config.DAILY_BURST)
        schedule = []
        for sport, evs in self.store.tracked_upcoming_by_sport(now).items():
            mins = min((parse(e["commence_time"]) - now).total_seconds() / 60 for e in evs)
            every = budget.poll_interval_minutes(mins)
            last = self.store.last_odds_poll(sport)
            nxt = now if last is None else max(now, last + timedelta(minutes=every or 0))
            schedule.append({
                "sport_key": sport, "tracked_events": len(evs),
                "minutes_to_next_kickoff": round(mins), "poll_every_minutes": every,
                "last_poll": iso(last) if last else None, "next_poll": iso(nxt),
                "last_skip_reason": self.last_skip.get(sport),
            })
        return {
            "demo": self.client is None,
            "remaining": remaining,
            "reserve": config.RESERVE_CREDITS,
            "spent_today": self.store.spent_since(midnight),
            "daily_allowance": round(allowance, 1),
            "cycle_resets": iso(budget.cycle_end(now, config.RESET_DAY)),
            "cost_per_poll": config.estimated_cost(),
            "bookmakers": config.BOOKMAKERS,
            "exchanges": sorted(config.EXCHANGES),
            "markets": config.MARKETS,
            "sports": config.SPORTS,
            "schedule": schedule,
        }

    # ---- API actions ---------------------------------------------------
    def _require_client(self) -> OddsApiClient:
        if self.client is None:
            raise OddsApiError("Demo mode: set ODDS_API_KEY to call the real API")
        return self.client

    async def refresh_fixtures(self, sport_key: str) -> list[dict]:
        client = self._require_client()
        now = self.now()
        try:
            events, usage = await client.events(sport_key)
        except OddsApiError as e:
            self.store.log_call(now, "events", sport_key, None, None, None, False, str(e))
            raise
        self.store.log_call(now, "events", sport_key, usage.last, usage.remaining, usage.used, True,
                            f"{len(events)} fixtures")
        self.store.upsert_events(sport_key, events)
        return self.store.events(sport_key)

    async def poll_sport(self, sport_key: str, manual: bool = False) -> dict:
        """One /odds call covering every tracked upcoming event in this sport."""
        client = self._require_client()
        now = self.now()
        events = self.store.tracked_upcoming_by_sport(now).get(sport_key, [])
        if not events:
            return {"polled": False, "reason": "no tracked upcoming events"}
        mins = min((parse(e["commence_time"]) - now).total_seconds() / 60 for e in events)
        cost = config.estimated_cost()
        remaining = self.remaining()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        allowance = budget.daily_allowance(remaining, config.RESERVE_CREDITS, now,
                                           config.RESET_DAY, config.DAILY_BURST)
        ok, reason = budget.can_spend(cost, remaining, config.RESERVE_CREDITS,
                                      self.store.spent_since(midnight), allowance, mins,
                                      config.PRIORITY_WINDOW_MIN, manual=manual)
        if not ok:
            self.last_skip[sport_key] = reason
            return {"polled": False, "reason": reason}
        try:
            payload, usage = await client.odds(sport_key, [e["id"] for e in events])
        except OddsApiError as e:
            self._failed_at[sport_key] = now
            self.store.log_call(now, "odds", sport_key, None, None, None, False, str(e))
            raise
        rows = normalize_odds(payload, iso(now))
        self.store.upsert_events(sport_key, [
            {k: ev.get(k) for k in ("id", "sport_title", "home_team", "away_team", "commence_time")}
            for ev in payload if ev.get("id") and ev.get("commence_time")
        ])
        self.store.add_snapshots(rows)
        self.store.log_call(now, "odds", sport_key, usage.last if usage.last is not None else cost,
                            usage.remaining, usage.used, True,
                            f"{len(payload)} events, {len(rows)} prices ({reason})")
        self.last_skip.pop(sport_key, None)
        self._failed_at.pop(sport_key, None)
        return {"polled": True, "reason": reason, "events": len(payload), "prices": len(rows),
                "cost": usage.last, "remaining": usage.remaining}

    # ---- background loop ----------------------------------------------
    async def tick(self) -> list[dict]:
        results = []
        now = self.now()
        for sport, evs in self.store.tracked_upcoming_by_sport(now).items():
            failed = self._failed_at.get(sport)
            if failed and now - failed < FAILURE_COOLDOWN:
                continue
            mins = min((parse(e["commence_time"]) - now).total_seconds() / 60 for e in evs)
            if not budget.is_due(self.store.last_odds_poll(sport), now, mins):
                continue
            try:
                results.append({"sport": sport, **await self.poll_sport(sport)})
            except OddsApiError as e:
                log.warning("poll %s failed: %s", sport, e)
                results.append({"sport": sport, "polled": False, "reason": str(e)})
        return results

    async def _run(self) -> None:
        while True:
            try:
                for r in await self.tick():
                    log.info("tick: %s", r)
            except Exception:  # keep the loop alive no matter what
                log.exception("tick crashed")
            await asyncio.sleep(config.LOOP_SECONDS)

    def start(self) -> None:
        if self.client is not None and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
