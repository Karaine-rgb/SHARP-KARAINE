"""How often the engine's favourite, the steam signal and the two together were right.

Pure functions of a match's main-line snapshots and its final score, so the
tally can be recomputed for any round at any time (nothing is stored).

Definitions (fixed here, shown on the dashboard):
  - Result side: home / draw / away from the final score.
  - Engine pick: favorite_strength()'s favourite (opening AH favourite, with the
    lead-change override). A pick'em with no pick is not counted as right or wrong.
    The pick is right when that side won (a draw is a miss).
  - Steam: the signal names every side that had a steam move (home, draw and/or
    away). It is right when the side that won was ANY of the steaming sides; the
    size of the move is not used. Matches where no side steamed are not counted.
    Because several sides can steam, this is a looser test than a single pick;
    avg_sides reports how many of the three sides it covers on average and
    chance_right how many matches a blind pick of the same number of sides
    would get right (covered sides / 3), so the hit count can be judged fairly.
  - Converged: the engine's favourite is also a steaming side. Right when that
    favourite won. A subset of both signals' matches.
"""
from __future__ import annotations

from app.signals import favorite_strength, steam_moves


def result_side(home_score, away_score) -> str | None:
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return "home"
    if away_score > home_score:
        return "away"
    return "draw"


def read_match(spread_series: list[dict], moneyline_series: list[dict]) -> dict:
    """{"engine": favourite side or None, "steam_sides": [sides that had a steam move]}"""
    fav = favorite_strength(spread_series, moneyline_series)
    return {
        "engine": fav.get("favorite"),
        "steam_sides": [m["side"] for m in steam_moves(moneyline_series)],
    }


def tally(matches: list[dict]) -> dict:
    """matches: [{"result": side, "engine": side|None, "steam_sides": [..]}] (settled matches only)."""
    engine_picks = engine_right = 0
    steam_flagged = steam_right = steam_sides_total = 0
    conv = conv_right = 0
    for m in matches:
        res, pick, sides = m["result"], m["engine"], set(m["steam_sides"])
        if pick is not None:
            engine_picks += 1
            engine_right += pick == res
        if sides:
            steam_flagged += 1
            steam_sides_total += len(sides)
            steam_right += res in sides
        if pick is not None and pick in sides:
            conv += 1
            conv_right += pick == res
    return {
        "settled": len(matches),
        "engine": {"picks": engine_picks, "right": int(engine_right), "no_pick": len(matches) - engine_picks},
        "steam": {
            "flagged": steam_flagged,
            "right": int(steam_right),
            "no_steam": len(matches) - steam_flagged,
            "avg_sides": round(steam_sides_total / steam_flagged, 2) if steam_flagged else None,
            # hits a blind pick of the same NUMBER of sides (any sides, equally likely) would get on average
            "chance_right": round(steam_sides_total / 3.0, 1),
        },
        "converged": {"count": conv, "right": int(conv_right)},
    }
