"""Client for Pinnacle's undocumented Arcadia guest API.

This is not a documented/supported integration - Pinnacle can change the
schema, rotate the guest key, or rate-limit/block this without notice.
Everything here is written against the schema the user captured from a
prior working build; it has NOT been exercised against a live response
from this environment (network egress here is blocked to everything
outside a small package-registry allowlist). Run this for real and report
back any field/shape mismatch so it can be corrected against ground truth.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger("pinnacle_client")


class ArcadiaError(Exception):
    pass


class ArcadiaRateLimited(ArcadiaError):
    pass


class ArcadiaAuthError(ArcadiaError):
    pass


class ArcadiaClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.arcadia_api_key
        self.base_url = (base_url or settings.arcadia_base_url).rstrip("/")
        self._client = httpx.AsyncClient(timeout=15.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "User-Agent": "Mozilla/5.0 (sharp-karaine tracker)",
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None, max_retries: int = 4) -> dict | list:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = await self._client.get(url, headers=self._headers(), params=params)
            except httpx.TransportError as exc:
                if attempt > max_retries:
                    raise ArcadiaError(f"Network error calling {path}: {exc}") from exc
                await asyncio.sleep(min(2 ** attempt, 30))
                continue

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401 or resp.status_code == 403:
                server = resp.headers.get("server", "?")
                ctype = resp.headers.get("content-type", "?")
                snippet = resp.text[:200].replace("\n", " ")
                raise ArcadiaAuthError(
                    f"Arcadia auth rejected ({resp.status_code}) from server="
                    f"{server!r} content-type={ctype!r}. This is either a "
                    "rotated/expired guest key (update it in Settings) or an "
                    "anti-bot block on requests that don't originate from a "
                    "real pinnacle.com browser session - a challenge-page "
                    f"body below points to the latter, not the key. Body: {snippet!r}"
                )
            if resp.status_code == 429:
                if attempt > max_retries:
                    raise ArcadiaRateLimited(f"Rate limited on {path} after {attempt} attempts")
                retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                await asyncio.sleep(min(retry_after, 60))
                continue
            if resp.status_code >= 500:
                if attempt > max_retries:
                    raise ArcadiaError(f"{path} returned {resp.status_code} after {attempt} attempts")
                await asyncio.sleep(min(2 ** attempt, 30))
                continue

            raise ArcadiaError(f"Unexpected status {resp.status_code} calling {path}: {resp.text[:300]}")

    async def get_league_matchups(self, league_id: int) -> list[dict]:
        """GET /leagues/{league_id}/matchups

        Verified against a live response (2026-09). Returns a flat list
        mixing real fixtures with their "special" sub-markets (Draw No
        Bet, team props, etc.) - every special for a fixture repeats the
        same `parent` object holding the actual match info. Consumers
        must resolve through `entry.parent or entry` and dedupe by that
        resolved id; team names are at `<resolved>.participants[]` as
        `{alignment: "home"|"away", name}`, kickoff at
        `<resolved>.startTime`, league at `entry.league.{id,name}`. See
        the dedup/resolve logic in frontend/app.js's discovery handler.
        """
        data = await self._get(f"/leagues/{league_id}/matchups")
        if isinstance(data, dict):
            data = data.get("matchups", data.get("data", []))
        return data or []

    async def get_matchup_markets(self, matchup_id: int) -> list[dict]:
        """GET /matchups/{matchup_id}/markets/related/straight

        Verified against a live response (2026-09) - and it does NOT
        return only this matchup's markets. Despite the URL naming one
        matchup, the response includes markets for many other unrelated
        matchups too (that's the "related" in the endpoint name - nearby
        matches on the same coupon), each carrying its own `matchupId`.
        Some of those unrelated entries use a completely different price
        shape (`participantId`-keyed, for markets with >2/3 outcomes) and
        many omit `version` entirely. None of that is meaningful for the
        match we actually asked about, so filter down to just it here -
        everything downstream (ingest, signals) assumes it only ever sees
        the requested matchup's own markets.
        """
        data = await self._get(f"/matchups/{matchup_id}/markets/related/straight")
        if isinstance(data, dict):
            data = data.get("markets", data.get("data", []))
        return [m for m in (data or []) if m.get("matchupId") == matchup_id]
