"""Adaptive-interval background poller.

Per the spec: 30s base interval, quiet backoff +15s per cycle with nothing
new up to a 120s cap, reset to base the moment a market changes, 1.0-3.5s
random jitter between matches (folded into each match's own schedule
rather than a blocking sleep, so N matches don't serialize behind each
other), and exponential backoff on auth/rate-limit errors.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from app import db, ingest, signals, telegram
from app.config import settings
from app.pinnacle_client import ArcadiaAuthError, ArcadiaClient, ArcadiaError
from app.settings_store import get_arcadia_api_key
from app.ws import manager

logger = logging.getLogger("poller")

TICK_SECONDS = 5.0


class MatchState:
    __slots__ = ("interval", "next_due", "error_streak")

    def __init__(self, base_interval: float):
        self.interval = base_interval
        self.next_due = datetime.now(timezone.utc)
        self.error_streak = 0


class Poller:
    def __init__(self) -> None:
        self._states: dict[int, MatchState] = {}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._client: ArcadiaClient | None = None
        self.force_poll_ids: set[int] = set()

    async def start(self) -> None:
        self._client = ArcadiaClient(api_key=await get_arcadia_api_key())
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        if self._client:
            await self._client.aclose()

    def force_poll(self, matchup_id: int) -> None:
        self.force_poll_ids.add(matchup_id)

    async def refresh_client(self) -> None:
        """Rebuild the Arcadia client after a Settings-panel key change."""
        old_client = self._client
        self._client = ArcadiaClient(api_key=await get_arcadia_api_key())
        if old_client:
            await old_client.aclose()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("Poller tick failed unexpectedly")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=TICK_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        rows = await db.fetch(
            "select id, pinnacle_matchup_id, home_team, away_team, start_time "
            "from matchups where is_monitored = true"
        )
        now = datetime.now(timezone.utc)
        expiry = timedelta(hours=settings.auto_expire_hours_after_kickoff)
        for row in rows:
            matchup_id = row["id"]
            if now > row["start_time"] + expiry:
                await self._auto_unmonitor(row, "past the auto-expiry window after kickoff")
                continue
            state = self._states.setdefault(matchup_id, MatchState(settings.poll_base_interval))
            forced = matchup_id in self.force_poll_ids
            if not forced and now < state.next_due:
                continue
            self.force_poll_ids.discard(matchup_id)
            await self._poll_one(row, state, now)

    async def _auto_unmonitor(self, row, reason: str) -> None:
        matchup_id = row["id"]
        await db.execute("update matchups set is_monitored = false where id = $1", matchup_id)
        self._states.pop(matchup_id, None)
        logger.info(
            "Auto-unmonitored matchup %s (%s vs %s): %s",
            matchup_id, row["home_team"], row["away_team"], reason,
        )
        await manager.broadcast({"type": "auto_unmonitored", "matchup_id": matchup_id, "reason": reason})

    async def _poll_one(self, row, state: MatchState, now: datetime) -> None:
        matchup_id = row["id"]
        jitter = random.uniform(settings.poll_jitter_min, settings.poll_jitter_max)
        try:
            raw_markets = await self._client.get_matchup_markets(row["pinnacle_matchup_id"])
            if not raw_markets and now >= row["start_time"]:
                # Pinnacle has pulled the match off the board entirely (fully
                # settled) - no point waiting out the rest of the auto-expiry
                # window polling a match with nothing left to poll.
                await self._auto_unmonitor(row, "Pinnacle returned no markets (settled)")
                return
            changed = await ingest.ingest_matchup_markets(matchup_id, raw_markets)
            result = await signals.compute_and_store_score(matchup_id, row["start_time"])
            await telegram.maybe_alert_tier_change(
                matchup_id,
                row["home_team"],
                row["away_team"],
                result["tier"],
                _summarize(result),
            )

            state.error_streak = 0
            if changed:
                state.interval = settings.poll_base_interval
            else:
                state.interval = min(state.interval + settings.poll_backoff_step, settings.poll_max_interval)
            state.next_due = now + timedelta(seconds=state.interval + jitter)

            await manager.broadcast(
                {
                    "type": "match_update",
                    "matchup_id": matchup_id,
                    "changed": bool(changed),
                    "tier": result["tier"],
                    "sharp_side": result["sharp_side"],
                    "total_score": result["total_score"],
                }
            )
        except ArcadiaAuthError as exc:
            logger.error("Arcadia auth error for matchup %s: %s", matchup_id, exc)
            state.error_streak += 1
            state.next_due = now + timedelta(seconds=settings.poll_max_interval)
            await manager.broadcast({"type": "error", "matchup_id": matchup_id, "message": str(exc)})
        except ArcadiaError as exc:
            logger.warning("Arcadia error for matchup %s: %s", matchup_id, exc)
            state.error_streak += 1
            backoff = min(settings.poll_max_interval * (2 ** min(state.error_streak, 4)), 1800)
            state.next_due = now + timedelta(seconds=backoff)
        except Exception:
            logger.exception("Unexpected error polling matchup %s", matchup_id)
            state.error_streak += 1
            state.next_due = now + timedelta(seconds=settings.poll_max_interval)


def _summarize(result: dict) -> str:
    parts = [f"score={result['total_score']:.1f}"]
    if result.get("ah", {}).get("direction"):
        parts.append(f"AH shift {result['ah']['shift']:+.2f} -> {result['ah']['direction']}")
    if result.get("x2", {}).get("direction"):
        parts.append(f"1X2 displacement {result['x2']['magnitude']:.2f}pp -> {result['x2']['direction']}")
    return ", ".join(parts)


poller = Poller()
