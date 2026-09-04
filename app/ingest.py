"""Normalize raw Arcadia market payloads and diff them against what's
already stored, so only genuinely changed market versions get written.

Verified against a live response (2026-09). Two things the original spec
got wrong, discovered from a real crash:

1. `version` is NOT reliably present on every market object, and where it
   IS present it is NOT per-line - Pinnacle bumps the same version number
   across *every* market for a matchup when any one of them changes (a
   single spread market can have 8+ simultaneous alternate lines all
   sharing type=spread/period=0/isAlternate=true, and in a real response
   they all shared one identical version value). Grouping by
   (market_type, period, is_alternate) therefore collapses all of a
   market's alternate lines onto one key, silently overwriting one
   another. The real unique identity for a specific line is Pinnacle's
   own `key` string (e.g. "s;0;s;1.25", "s;0;ou;3.5") - use that instead.
2. Missing `version` is treated as "always changed" rather than crashing,
   since we can't tell whether it changed without one.

Functions are split into pure (no I/O, unit-testable) and DB-touching
halves, marked below.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.odds import american_to_decimal, power_devig, implied_prob


def _parse_iso(ts: str | None) -> datetime | None:
    """Arcadia timestamps (cutoffAt, startTime) are ISO 8601 strings, often
    with a trailing 'Z'. asyncpg needs an actual datetime for timestamptz
    columns, not a string - replace 'Z' with an explicit UTC offset for
    fromisoformat compatibility across Python versions.
    """
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _market_key(market: dict) -> str:
    """The real per-line identity. Falls back to a constructed key in the
    same style on the rare chance `key` is absent, so tracking degrades
    gracefully instead of crashing - though every market seen from the
    requested matchup itself has carried a `key`.
    """
    key = market.get("key")
    if key:
        return key
    return f"{market['type']};{market.get('period', 0)};{market.get('isAlternate')};{market.get('matchupId')}"


def _extract_limit_amount(market: dict) -> float | None:
    for lim in market.get("limits", []) or []:
        if lim.get("type") == "maxRiskStake":
            amt = lim.get("amount")
            return float(amt) if amt is not None else None
    return None


def normalize_market(matchup_id: int, market: dict) -> dict:
    """Turn one raw market object into our normalized snapshot shape.

    Does not decide whether it's new/changed - see diff_changed_markets.
    """
    prices_by_designation: dict[str, dict[str, Any]] = {}
    for price in market.get("prices", []) or []:
        designation = price.get("designation")
        american = price.get("price")
        if designation is None or american is None:
            continue
        prices_by_designation[designation] = {
            "price_american": american,
            "decimal": american_to_decimal(float(american)),
            "points": price.get("points"),
        }

    market_type = market["type"]
    home_price = draw_price = away_price = home_points = None

    if market_type == "moneyline":
        if "home" in prices_by_designation:
            home_price = prices_by_designation["home"]["decimal"]
        if "draw" in prices_by_designation:
            draw_price = prices_by_designation["draw"]["decimal"]
        if "away" in prices_by_designation:
            away_price = prices_by_designation["away"]["decimal"]
    elif market_type == "spread":
        if "home" in prices_by_designation:
            home_price = prices_by_designation["home"]["decimal"]
            home_points = prices_by_designation["home"]["points"]
        if "away" in prices_by_designation:
            away_price = prices_by_designation["away"]["decimal"]
    elif market_type in ("total", "team_total"):
        # No home/away concept - map over->home slot, under->away slot so
        # the generic numeric columns stay usable. raw_json keeps the
        # original designations for anything that needs to display them
        # correctly (the frontend should label these as Over/Under, not
        # Home/Away).
        if "over" in prices_by_designation:
            home_price = prices_by_designation["over"]["decimal"]
            home_points = prices_by_designation["over"]["points"]
        if "under" in prices_by_designation:
            away_price = prices_by_designation["under"]["decimal"]
            if home_points is None:
                home_points = prices_by_designation["under"]["points"]

    version = market.get("version")
    return {
        "matchup_id": matchup_id,
        "market_key": _market_key(market),
        "market_type": market_type,
        "period": int(market.get("period", 0)),
        "is_alternate": bool(market.get("isAlternate", False)),
        "version": int(version) if version is not None else None,
        "status": market.get("status"),
        "cutoff_at": _parse_iso(market.get("cutoffAt")),
        "home_price": home_price,
        "draw_price": draw_price,
        "away_price": away_price,
        "home_points": home_points,
        "limit_amount": _extract_limit_amount(market),
        "raw": market,
        "prices_by_designation": prices_by_designation,
    }


def add_fair_probs(snapshot: dict) -> dict:
    """Attach de-vigged fair probabilities where enough live prices exist.

    Suspended markets or markets missing a side (e.g. mid-tranche) are
    left with fair_*_prob = None rather than guessed at.
    """
    prices = [
        p for p in (snapshot["home_price"], snapshot["draw_price"], snapshot["away_price"]) if p
    ]
    snapshot["fair_home_prob"] = snapshot["fair_draw_prob"] = snapshot["fair_away_prob"] = None
    if snapshot.get("status") == "suspended":
        return snapshot
    if snapshot["market_type"] == "moneyline" and all(
        snapshot[k] for k in ("home_price", "draw_price", "away_price")
    ):
        raw_probs = [implied_prob(snapshot[k]) for k in ("home_price", "draw_price", "away_price")]
        fair = power_devig(raw_probs)
        snapshot["fair_home_prob"], snapshot["fair_draw_prob"], snapshot["fair_away_prob"] = fair
    elif snapshot["market_type"] in ("spread", "total", "team_total") and snapshot["home_price"] and snapshot["away_price"]:
        raw_probs = [implied_prob(snapshot["home_price"]), implied_prob(snapshot["away_price"])]
        fair = power_devig(raw_probs)
        snapshot["fair_home_prob"], snapshot["fair_away_prob"] = fair
    return snapshot


def diff_changed_markets(
    raw_markets: list[dict], last_versions: dict[str, int | None]
) -> list[dict]:
    """Return only markets whose version is new or has changed. A market
    with no version at all is always treated as changed, since there's no
    way to tell otherwise - better to over-persist a few extra rows than
    silently drop a real line (or crash, as this used to).
    """
    changed = []
    for market in raw_markets:
        key = _market_key(market)
        version = market.get("version")
        if version is None or last_versions.get(key) != version:
            changed.append(market)
    return changed


def select_main_line(normalized_markets: list[dict], market_type: str, period: int = 0) -> dict | None:
    """Pick the 'main' line for spread/total markets: prefer isAlternate
    == False, tie-break by points closest to zero (per the user's rule
    that a main line is "the spread market with points value closest to
    0" - accounts for cases where isAlternate alone doesn't disambiguate).
    Moneyline markets don't have alternates in the same sense; there's
    normally exactly one per period.
    """
    candidates = [
        m for m in normalized_markets if m["market_type"] == market_type and m["period"] == period
    ]
    if not candidates:
        return None
    non_alt = [m for m in candidates if not m["is_alternate"]]
    pool = non_alt or candidates
    if market_type == "moneyline":
        return pool[0]
    return min(pool, key=lambda m: abs(m["home_points"]) if m["home_points"] is not None else float("inf"))


# ---------------------------------------------------------------------------
# DB-touching functions below. Kept thin and separate so the logic above is
# unit-testable without a database.
# ---------------------------------------------------------------------------

from app import db  # noqa: E402


async def get_last_versions(matchup_id: int) -> dict[str, int | None]:
    rows = await db.fetch(
        """
        select distinct on (market_key) market_key, version
        from market_snapshots
        where matchup_id = $1
        order by market_key, captured_at desc
        """,
        matchup_id,
    )
    return {r["market_key"]: r["version"] for r in rows}


async def persist_snapshots(snapshots: list[dict]) -> None:
    if not snapshots:
        return
    await db.executemany(
        """
        insert into market_snapshots (
            matchup_id, market_key, market_type, period, is_alternate, version, status,
            cutoff_at, captured_at, raw_json, home_price, draw_price, away_price,
            home_points, limit_amount, fair_home_prob, fair_draw_prob, fair_away_prob
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14,$15,$16,$17,$18)
        """,
        [
            (
                s["matchup_id"],
                s["market_key"],
                s["market_type"],
                s["period"],
                s["is_alternate"],
                s["version"],
                s.get("status"),
                s.get("cutoff_at"),
                datetime.now(timezone.utc),
                db.to_jsonb(s["raw"]),
                s["home_price"],
                s["draw_price"],
                s["away_price"],
                s["home_points"],
                s["limit_amount"],
                s.get("fair_home_prob"),
                s.get("fair_draw_prob"),
                s.get("fair_away_prob"),
            )
            for s in snapshots
        ],
    )


async def ingest_matchup_markets(matchup_id: int, raw_markets: list[dict]) -> list[dict]:
    """Full pipeline for one matchup's poll cycle: diff -> normalize ->
    devig -> persist. Returns the snapshots that were actually written
    (empty list means nothing changed this cycle).
    """
    last_versions = await get_last_versions(matchup_id)
    changed_raw = diff_changed_markets(raw_markets, last_versions)
    snapshots = [add_fair_probs(normalize_market(matchup_id, m)) for m in changed_raw]
    await persist_snapshots(snapshots)
    return snapshots
