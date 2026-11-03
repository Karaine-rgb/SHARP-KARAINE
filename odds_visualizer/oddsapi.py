"""Thin async client for The Odds API v4 + response normalization."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from . import config


class OddsApiError(Exception):
    pass


@dataclass
class Usage:
    """Quota headers returned on every response. These are the source of truth."""
    remaining: int | None
    used: int | None
    last: int | None

    @classmethod
    def from_headers(cls, headers: httpx.Headers) -> "Usage":
        def num(name: str) -> int | None:
            v = headers.get(name)
            try:
                return int(float(v)) if v is not None else None
            except ValueError:
                return None
        return cls(num("x-requests-remaining"), num("x-requests-used"), num("x-requests-last"))


class OddsApiClient:
    def __init__(self, api_key: str | None = None, base: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key if api_key is not None else config.ODDS_API_KEY
        self.base = base or config.ODDS_API_BASE
        self._transport = transport  # tests inject a MockTransport

    async def _get(self, path: str, params: dict[str, Any]) -> tuple[Any, Usage]:
        if not self.api_key:
            raise OddsApiError("ODDS_API_KEY is not set")
        q = {"apiKey": self.api_key, **{k: v for k, v in params.items() if v is not None}}
        async with httpx.AsyncClient(timeout=20, transport=self._transport) as client:
            resp = await client.get(f"{self.base}{path}", params=q)
        usage = Usage.from_headers(resp.headers)
        if resp.status_code != 200:
            hint = {401: "bad or missing API key", 429: "quota used up or rate limited",
                    422: "invalid parameter"}.get(resp.status_code, "")
            raise OddsApiError(f"HTTP {resp.status_code} {hint}: {resp.text[:300]}".strip())
        return resp.json(), usage

    async def sports(self) -> tuple[list[dict], Usage]:
        return await self._get("/sports", {})

    async def events(self, sport_key: str) -> tuple[list[dict], Usage]:
        return await self._get(f"/sports/{sport_key}/events", {"dateFormat": "iso"})

    async def odds(self, sport_key: str, event_ids: list[str], bookmakers: list[str] | None = None,
                   markets: list[str] | None = None) -> tuple[list[dict], Usage]:
        return await self._get(f"/sports/{sport_key}/odds", {
            "bookmakers": ",".join(bookmakers or config.BOOKMAKERS),
            "markets": ",".join(markets or config.MARKETS),
            "eventIds": ",".join(event_ids) if event_ids else None,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        })


def normalize_odds(payload: list[dict], fetched_at: str) -> list[dict]:
    """Flatten /odds JSON into one row per (event, bookmaker, market, outcome)."""
    rows: list[dict] = []
    for ev in payload or []:
        for bm in ev.get("bookmakers") or []:
            for mk in bm.get("markets") or []:
                for oc in mk.get("outcomes") or []:
                    price = oc.get("price")
                    if price is None:
                        continue
                    rows.append({
                        "event_id": ev.get("id"),
                        "bookmaker": bm.get("key"),
                        "bookmaker_title": bm.get("title") or bm.get("key"),
                        "market": mk.get("key"),
                        "outcome": oc.get("name"),
                        "point": oc.get("point"),
                        "price": float(price),
                        "bm_last_update": mk.get("last_update") or bm.get("last_update"),
                        "fetched_at": fetched_at,
                    })
    return rows
