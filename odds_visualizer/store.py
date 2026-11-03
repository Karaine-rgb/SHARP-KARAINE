"""SQLite storage. The free plan has no historical odds, so every poll is
saved here - this table *is* your movement history."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    sport_key TEXT NOT NULL,
    sport_title TEXT,
    home_team TEXT,
    away_team TEXT,
    commence_time TEXT NOT NULL,
    tracked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    bookmaker_title TEXT,
    market TEXT NOT NULL,
    outcome TEXT NOT NULL,
    point REAL,
    price REAL NOT NULL,
    bm_last_update TEXT,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_snap_event ON snapshots(event_id, market, fetched_at);
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    sport_key TEXT,
    cost INTEGER,
    remaining INTEGER,
    used INTEGER,
    ok INTEGER NOT NULL,
    note TEXT
);
"""


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def _write(self, sql: str, args: tuple | list = (), many: bool = False) -> None:
        with self.lock:
            (self.conn.executemany if many else self.conn.execute)(sql, args)
            self.conn.commit()

    # ---- events -------------------------------------------------------
    def upsert_events(self, sport_key: str, events: list[dict]) -> None:
        self._write(
            """INSERT INTO events (id, sport_key, sport_title, home_team, away_team, commence_time)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET commence_time=excluded.commence_time,
                 home_team=excluded.home_team, away_team=excluded.away_team""",
            [(e["id"], sport_key, e.get("sport_title"), e.get("home_team"), e.get("away_team"),
              e["commence_time"]) for e in events],
            many=True,
        )

    def set_tracked(self, event_id: str, tracked: bool) -> None:
        self._write("UPDATE events SET tracked=? WHERE id=?", (int(tracked), event_id))

    def events(self, sport_key: str | None = None, tracked_only: bool = False) -> list[dict]:
        sql, args = "SELECT * FROM events WHERE 1=1", []
        if sport_key:
            sql += " AND sport_key=?"; args.append(sport_key)
        if tracked_only:
            sql += " AND tracked=1"
        return self._all(sql + " ORDER BY commence_time", tuple(args))

    def event(self, event_id: str) -> dict | None:
        rows = self._all("SELECT * FROM events WHERE id=?", (event_id,))
        return rows[0] if rows else None

    def tracked_upcoming_by_sport(self, now: datetime) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for e in self.events(tracked_only=True):
            if parse(e["commence_time"]) > now:
                out.setdefault(e["sport_key"], []).append(e)
        return out

    # ---- snapshots ----------------------------------------------------
    def add_snapshots(self, rows: list[dict]) -> None:
        self._write(
            """INSERT INTO snapshots (event_id, bookmaker, bookmaker_title, market, outcome, point,
                 price, bm_last_update, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            [(r["event_id"], r["bookmaker"], r["bookmaker_title"], r["market"], r["outcome"],
              r["point"], r["price"], r["bm_last_update"], r["fetched_at"]) for r in rows],
            many=True,
        )

    def snapshots(self, event_id: str, market: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM snapshots WHERE event_id=?", [event_id]
        if market:
            sql += " AND market=?"; args.append(market)
        return self._all(sql + " ORDER BY fetched_at, id", tuple(args))

    def markets_for(self, event_id: str) -> list[str]:
        return [r["market"] for r in self._all(
            "SELECT DISTINCT market FROM snapshots WHERE event_id=? ORDER BY market", (event_id,))]

    def snapshot_counts(self) -> dict[str, int]:
        return {r["event_id"]: r["n"] for r in self._all(
            "SELECT event_id, COUNT(DISTINCT fetched_at) AS n FROM snapshots GROUP BY event_id")}

    # ---- api call log / budget ---------------------------------------
    def log_call(self, at: datetime, endpoint: str, sport_key: str | None, cost: int | None,
                 remaining: int | None, used: int | None, ok: bool, note: str = "") -> None:
        self._write(
            "INSERT INTO api_calls (at, endpoint, sport_key, cost, remaining, used, ok, note) VALUES (?,?,?,?,?,?,?,?)",
            (iso(at), endpoint, sport_key, cost, remaining, used, int(ok), note),
        )

    def calls(self, limit: int = 50) -> list[dict]:
        return self._all("SELECT * FROM api_calls ORDER BY id DESC LIMIT ?", (limit,))

    def last_known_remaining(self) -> int | None:
        rows = self._all("SELECT remaining FROM api_calls WHERE remaining IS NOT NULL ORDER BY id DESC LIMIT 1")
        return rows[0]["remaining"] if rows else None

    def spent_since(self, since: datetime) -> int:
        rows = self._all("SELECT COALESCE(SUM(cost),0) AS s FROM api_calls WHERE at >= ?", (iso(since),))
        return int(rows[0]["s"])

    def last_odds_poll(self, sport_key: str) -> datetime | None:
        rows = self._all(
            "SELECT at FROM api_calls WHERE endpoint='odds' AND sport_key=? AND ok=1 ORDER BY id DESC LIMIT 1",
            (sport_key,))
        return parse(rows[0]["at"]) if rows else None
