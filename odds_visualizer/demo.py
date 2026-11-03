"""Fake fixtures + fake odds history so the dashboard can be tried with
zero API credits. Everything here is made up."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from . import config
from .store import Store, iso

DEMO_EVENTS = [
    ("demo-1", "soccer_epl", "EPL", "Arsenal", "Chelsea", 5),
    ("demo-2", "soccer_epl", "EPL", "Everton", "Fulham", 26),
    ("demo-3", "soccer_spain_la_liga", "La Liga", "Sevilla", "Valencia", 50),
]
TITLES = {
    "pinnacle": "Pinnacle", "betfair_ex_uk": "Betfair Exchange (UK)", "betfair_ex_eu": "Betfair Exchange (EU)",
    "matchbook": "Matchbook", "smarkets": "Smarkets", "williamhill": "William Hill", "unibet_eu": "Unibet",
    "onexbet": "1xBet", "marathonbet": "Marathon Bet", "betsson": "Betsson",
}


def seed(store: Store, now: datetime) -> None:
    if store.events():
        return
    rng = random.Random(42)
    for eid, sport, title, home, away, hours_ahead in DEMO_EVENTS:
        ko = now + timedelta(hours=hours_ahead)
        store.upsert_events(sport, [{"id": eid, "sport_title": title, "home_team": home,
                                     "away_team": away, "commence_time": iso(ko)}])
        store.set_tracked(eid, True)
        fair = {home: 0.45, "Draw": 0.27, away: 0.28}
        drift = rng.choice([-1, 1]) * 0.08  # home prob drifts by this much (a "steam" move)
        start = now - timedelta(hours=48)
        steps = 30
        rows = []
        for i in range(steps + 1):
            t = start + (now - start) * i / steps
            frac = i / steps
            for bm in config.BOOKMAKERS:
                is_ex = bm in config.EXCHANGES
                # exchanges react first, books follow ~4 steps later
                lag = 0 if is_ex else 4 / steps
                moved = max(0.0, min(1.0, (frac - 0.5 - lag) * 3))
                p = dict(fair)
                p[home] += drift * moved
                p[away] -= drift * moved
                margin = 1.005 if is_ex else (1.02 if bm == "pinnacle" else 1.06)
                for name, prob in p.items():
                    noise = rng.uniform(-0.004, 0.004)
                    price = round(1 / max(0.02, (prob + noise) * margin), 2)
                    rows.append({"event_id": eid, "bookmaker": bm, "bookmaker_title": TITLES.get(bm, bm),
                                 "market": "h2h", "outcome": name, "point": None, "price": price,
                                 "bm_last_update": iso(t), "fetched_at": iso(t)})
        store.add_snapshots(rows)
