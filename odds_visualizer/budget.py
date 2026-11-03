"""Credit budget + poll scheduling. Pure functions, no I/O.

Think of the 500 credits as monthly pocket money:
- `poll_interval_minutes` decides how often we *want* to look at prices
  (rarely when kickoff is days away, often in the last hour).
- `can_spend` decides whether we can *afford* it right now.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

# (max minutes to kickoff, poll every N minutes). First match wins.
INTERVAL_TIERS: list[tuple[int, int]] = [
    (60, 20),      # last hour: every 20 min
    (180, 45),     # 1-3h out: every 45 min
    (360, 90),     # 3-6h out: every 1.5h
    (1440, 240),   # 6-24h out: every 4h
    (2880, 720),   # 1-2 days out: every 12h
]
FAR_INTERVAL = 1440  # more than 2 days out: once a day


def poll_interval_minutes(minutes_to_kickoff: float) -> int | None:
    """How often to poll, given the nearest kickoff. None = stop (kicked off)."""
    if minutes_to_kickoff <= 0:
        return None
    for upper, every in INTERVAL_TIERS:
        if minutes_to_kickoff <= upper:
            return every
    return FAR_INTERVAL


def is_due(last_poll: datetime | None, now: datetime, minutes_to_kickoff: float) -> bool:
    every = poll_interval_minutes(minutes_to_kickoff)
    if every is None:
        return False
    if last_poll is None:
        return True
    return now - last_poll >= timedelta(minutes=every)


def cycle_end(now: datetime, reset_day: int) -> datetime:
    """Next quota reset (midnight UTC on `reset_day`, clamped to month length)."""
    def on(year: int, month: int) -> datetime:
        # clamp e.g. reset_day=31 in a 30-day month
        nxt = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
        last_day = (nxt - timedelta(days=1)).day
        return datetime(year, month, min(reset_day, last_day), tzinfo=timezone.utc)

    candidate = on(now.year, now.month)
    if candidate <= now:
        y, m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
        candidate = on(y, m)
    return candidate


def daily_allowance(remaining: int, reserve: int, now: datetime, reset_day: int, burst: float) -> float:
    """Max credits one day may use: average share of what's left x burst."""
    days_left = max(1, math.ceil((cycle_end(now, reset_day) - now).total_seconds() / 86400))
    spendable = max(0, remaining - reserve)
    return min(spendable, spendable / days_left * burst)


def can_spend(
    cost: int,
    remaining: int,
    reserve: int,
    spent_today: int,
    allowance: float,
    minutes_to_kickoff: float,
    priority_window: int,
    manual: bool = False,
) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    if remaining - cost < reserve and not manual:
        return False, f"would dip into reserve ({remaining} left, reserve {reserve})"
    if remaining - cost < 0:
        return False, f"not enough credits ({remaining} left, need {cost})"
    if manual:
        return True, "manual poll"
    if spent_today + cost <= allowance:
        return True, "within daily share"
    if minutes_to_kickoff <= priority_window:
        return True, "near kickoff (priority)"
    return False, f"daily share used ({spent_today}/{allowance:.1f})"
