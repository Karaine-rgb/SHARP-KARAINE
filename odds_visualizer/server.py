"""FastAPI app for the odds movement visualizer.

Run:  uvicorn odds_visualizer.server:app --reload --port 8010
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, demo
from .oddsapi import OddsApiClient, OddsApiError
from .store import Store
from .tracker import Tracker, utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"


def build_tracker() -> Tracker:
    if config.DEMO:
        store = Store(":memory:")
        demo.seed(store, utcnow())
        return Tracker(store, None)
    return Tracker(Store(config.DB_PATH), OddsApiClient())


tracker = build_tracker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    tracker.start()
    yield
    await tracker.stop()


app = FastAPI(title="Odds Movement Visualizer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
async def status():
    return tracker.budget_status()


@app.get("/api/calls")
async def calls(limit: int = 50):
    return tracker.store.calls(limit)


@app.get("/api/events")
async def events(sport_key: str | None = None, tracked: bool = False):
    counts = tracker.store.snapshot_counts()
    return [{**e, "snapshots": counts.get(e["id"], 0)}
            for e in tracker.store.events(sport_key, tracked_only=tracked)]


@app.post("/api/fixtures/{sport_key}")
async def refresh_fixtures(sport_key: str):
    try:
        return await tracker.refresh_fixtures(sport_key)
    except OddsApiError as e:
        raise HTTPException(400, str(e))


class TrackBody(BaseModel):
    tracked: bool


@app.post("/api/events/{event_id}/track")
async def track(event_id: str, body: TrackBody):
    if not tracker.store.event(event_id):
        raise HTTPException(404, "unknown event")
    tracker.store.set_tracked(event_id, body.tracked)
    return {"ok": True}


@app.post("/api/poll/{sport_key}")
async def poll(sport_key: str):
    try:
        return await tracker.poll_sport(sport_key, manual=True)
    except OddsApiError as e:
        raise HTTPException(400, str(e))


def outcome_label(s: dict) -> str:
    return s["outcome"] if s["point"] is None else f'{s["outcome"]} {s["point"]:g}'


@app.get("/api/events/{event_id}/series")
async def series(event_id: str, market: str | None = None):
    ev = tracker.store.event(event_id)
    if not ev:
        raise HTTPException(404, "unknown event")
    markets = tracker.store.markets_for(event_id)
    market = market or ("h2h" if "h2h" in markets else (markets[0] if markets else "h2h"))
    snaps = tracker.store.snapshots(event_id, market)

    data: dict[str, dict[str, list]] = {}
    titles: dict[str, str] = {}
    for s in snaps:
        label = outcome_label(s)
        titles[s["bookmaker"]] = s["bookmaker_title"] or s["bookmaker"]
        data.setdefault(label, {}).setdefault(s["bookmaker"], []).append([s["fetched_at"], s["price"]])

    # Order outcomes home, draw, away when we can.
    order = {ev["home_team"]: 0, "Draw": 1, ev["away_team"]: 2}
    outcomes = sorted(data, key=lambda o: (order.get(o, 3), o))

    summary = []
    for o in outcomes:
        for bm, pts in data[o].items():
            first, last = pts[0][1], pts[-1][1]
            summary.append({
                "outcome": o, "bookmaker": bm, "title": titles[bm],
                "exchange": bm in config.EXCHANGES, "open": first, "latest": last,
                "change_pct": round((last - first) / first * 100, 2),
                "implied_open": round(100 / first, 2), "implied_latest": round(100 / last, 2),
                "points": len(pts),
            })
    return {
        "event": ev, "markets": markets, "market": market, "outcomes": outcomes,
        "bookmakers": [{"key": k, "title": v, "exchange": k in config.EXCHANGES}
                       for k, v in sorted(titles.items(), key=lambda kv: kv[1].lower())],
        "series": data, "summary": summary,
        "polls": sorted({s["fetched_at"] for s in snaps}),
    }
