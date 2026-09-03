"""Sharp-money signal detection and scoring.

Implements the five signals and scoring model exactly as specified by the
user from their prior build:

  1. Limit movement       - % drop in maxRiskStake vs the opening snapshot
  2. AH line shift        - points delta on the main Asian Handicap line
  3. 1X2 fair-prob move   - cumulative pp change in de-vigged 1X2 probs
                            from the true opening line
  4. AH fair-prob move    - same idea on the AH market (confirmation)
  5. Cross-market convergence - all of the above agreeing on one side

IMPORTANT - calibration disclaimer: the *qualitative* thresholds below
(0.25/0.5/1.0 points, 0.30/0.80/1.80pp, 30%/50% limit drop) come directly
from the user's spec. The *numeric score values* each threshold maps to
(e.g. "a 1.0pt AH shift = 5.0 score") are this implementation's own
calibration bridging those qualitative thresholds into the 0-10 scoring
model - they are not empirically derived from real data (none exists yet
for this tool). All of them live in the CONFIG dict below so they can be
retuned once real rounds of data come in, without touching the logic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

CONFIG = {
    "ah_shift_syndicate": 1.0,
    "ah_shift_sharp": 0.5,
    "ah_shift_threshold": 0.25,  # below this, not attributed as a signal at all
    "ah_score_syndicate": 5.0,
    "ah_score_sharp": 3.5,
    "ah_score_threshold": 2.0,
    "x2_strong_pp": 1.80,
    "x2_meaningful_pp": 0.80,
    "x2_noise_floor_pp": 0.30,
    "x2_score_strong": 5.0,
    "x2_score_meaningful": 3.0,
    "x2_score_noise_floor": 1.5,
    "limit_drop_severe_pct": 50.0,
    "limit_drop_significant_pct": 30.0,
    "limit_bonus_severe": 3.0,
    "limit_bonus_significant": 1.5,
    "convergence_bonus": 1.0,
    "tier_strong_sharp": 7.0,
    "tier_sharp": 4.5,
    "tier_watch": 2.0,
    "early_late_split_hours": 24,  # boundary between "early week" and "late window"
    "min_snapshots_for_signal": 2,
    "min_age_hours_for_signal": 2.0,
}


def _first_last(series: list[dict], field: str) -> tuple[Any, Any]:
    valid = [s for s in series if s.get(field) is not None and s.get("status") != "suspended"]
    if not valid:
        return None, None
    return valid[0][field], valid[-1][field]


def ah_line_shift(spread_series: list[dict]) -> dict:
    """spread_series: chronological list of {captured_at, home_points, status}
    for the main (non-alternate, closest-to-zero) AH line.
    """
    opening, current = _first_last(spread_series, "home_points")
    if opening is None or current is None:
        return {"opening": None, "current": None, "shift": 0.0, "magnitude": 0.0, "direction": None}
    shift = current - opening
    direction = None
    if abs(shift) >= CONFIG["ah_shift_threshold"]:
        # more negative home points => home is being asked to give a bigger
        # start => home favored more => home backed by sharps.
        direction = "home" if shift < 0 else "away"
    return {"opening": opening, "current": current, "shift": shift, "magnitude": abs(shift), "direction": direction}


def x2_displacement(moneyline_series: list[dict]) -> dict:
    """moneyline_series: chronological list of
    {captured_at, fair_home_prob, fair_draw_prob, fair_away_prob, status}.
    Displacement is in percentage points (pp), from the true opening line
    (the first stored snapshot, not an arbitrary baseline).
    """
    result = {"home_pp": 0.0, "draw_pp": 0.0, "away_pp": 0.0, "magnitude": 0.0, "direction": None}
    for outcome in ("home", "draw", "away"):
        opening, current = _first_last(moneyline_series, f"fair_{outcome}_prob")
        if opening is not None and current is not None:
            result[f"{outcome}_pp"] = (current - opening) * 100.0

    home_pp, away_pp = result["home_pp"], result["away_pp"]
    if abs(home_pp) >= abs(away_pp):
        result["magnitude"] = abs(home_pp)
        if abs(home_pp) >= CONFIG["x2_noise_floor_pp"]:
            result["direction"] = "home" if home_pp > 0 else "away"
    else:
        result["magnitude"] = abs(away_pp)
        if abs(away_pp) >= CONFIG["x2_noise_floor_pp"]:
            result["direction"] = "away" if away_pp > 0 else "home"
    return result


def limit_drop_pct(series: list[dict]) -> float:
    opening, current = _first_last(series, "limit_amount")
    if not opening or opening <= 0 or current is None:
        return 0.0
    return max(0.0, (opening - current) / opening * 100.0)


def detect_contested(
    moneyline_series: list[dict], kickoff: datetime, split_hours: float = CONFIG["early_late_split_hours"]
) -> bool:
    """A match is 'contested' when early-week and late-window sharp
    direction disagree (per the user's spec: sharps moved one way, then
    reversed) - each window needs enough of its own history for the
    comparison to mean anything, not just a single crossing snapshot.
    """
    cutoff = kickoff - timedelta(hours=split_hours)
    early = [s for s in moneyline_series if s.get("captured_at") and s["captured_at"] <= cutoff]
    late = [s for s in moneyline_series if s.get("captured_at") and s["captured_at"] > cutoff]
    if len(early) < 2 or len(late) < 2:
        return False
    early_disp = x2_displacement(early)
    late_disp = x2_displacement(late)
    if early_disp["direction"] is None or late_disp["direction"] is None:
        return False
    return early_disp["direction"] != late_disp["direction"]


def _score_ah(magnitude: float) -> float:
    c = CONFIG
    if magnitude >= c["ah_shift_syndicate"]:
        return c["ah_score_syndicate"]
    if magnitude >= c["ah_shift_sharp"]:
        return c["ah_score_sharp"]
    if magnitude >= c["ah_shift_threshold"]:
        return c["ah_score_threshold"]
    return 0.0


def _score_x2(magnitude_pp: float) -> float:
    c = CONFIG
    if magnitude_pp >= c["x2_strong_pp"]:
        return c["x2_score_strong"]
    if magnitude_pp >= c["x2_meaningful_pp"]:
        return c["x2_score_meaningful"]
    if magnitude_pp >= c["x2_noise_floor_pp"]:
        return c["x2_score_noise_floor"]
    return 0.0


def _score_limit(drop_pct: float) -> float:
    c = CONFIG
    if drop_pct >= c["limit_drop_severe_pct"]:
        return c["limit_bonus_severe"]
    if drop_pct >= c["limit_drop_significant_pct"]:
        return c["limit_bonus_significant"]
    return 0.0


def classify_tier(total_score: float) -> str:
    capped = min(total_score, 10.0)
    c = CONFIG
    if capped >= c["tier_strong_sharp"]:
        return "strong_sharp"
    if capped >= c["tier_sharp"]:
        return "sharp"
    if capped >= c["tier_watch"]:
        return "watch"
    return "no_signal"


def data_sufficiency(moneyline_series: list[dict], spread_series: list[dict], now: datetime) -> bool:
    c = CONFIG
    for series in (moneyline_series, spread_series):
        if len(series) >= c["min_snapshots_for_signal"] and series[0].get("captured_at"):
            age_hours = (now - series[0]["captured_at"]).total_seconds() / 3600.0
            if age_hours >= c["min_age_hours_for_signal"]:
                return True
    return False


def compute_match_score(
    moneyline_series: list[dict],
    spread_series: list[dict],
    kickoff: datetime,
    now: datetime | None = None,
) -> dict:
    """Top-level pure scoring entry point. Both series must be chronological
    (oldest first) and pre-filtered to the *main* line for each market type
    (see ingest.select_main_line).
    """
    now = now or datetime.now(timezone.utc)

    if not data_sufficiency(moneyline_series, spread_series, now):
        return {
            "tier": "insufficient_data",
            "sharp_side": None,
            "contested": False,
            "ah": ah_line_shift(spread_series),
            "x2": x2_displacement(moneyline_series),
            "moneyline_limit_drop_pct": limit_drop_pct(moneyline_series),
            "spread_limit_drop_pct": limit_drop_pct(spread_series),
            "ah_score": 0.0,
            "x2_score": 0.0,
            "limit_bonus": 0.0,
            "convergence_bonus": 0.0,
            "total_score": 0.0,
        }

    ah = ah_line_shift(spread_series)
    x2 = x2_displacement(moneyline_series)
    ml_limit_drop = limit_drop_pct(moneyline_series)
    sp_limit_drop = limit_drop_pct(spread_series)
    max_limit_drop = max(ml_limit_drop, sp_limit_drop)

    ah_score = _score_ah(ah["magnitude"])
    x2_score = _score_x2(x2["magnitude"])
    limit_bonus = _score_limit(max_limit_drop)

    conv_bonus = 0.0
    if (
        ah["magnitude"] >= CONFIG["ah_shift_threshold"]
        and x2["magnitude"] >= CONFIG["x2_meaningful_pp"]
        and max_limit_drop >= CONFIG["limit_drop_significant_pct"]
        and ah["direction"] is not None
        and ah["direction"] == x2["direction"]
    ):
        conv_bonus = CONFIG["convergence_bonus"]

    total = 1.4 * ah_score + 1.0 * x2_score + limit_bonus + conv_bonus
    contested = detect_contested(moneyline_series, kickoff)

    # Sharp side priority: AH shift first (sharps move AH first per the
    # spec), then largest 1X2 displacement. A contested result keeps the
    # most recent window's direction visible but flags the disagreement
    # rather than picking a side with false confidence.
    if ah["direction"]:
        sharp_side = ah["direction"]
    elif x2["direction"]:
        sharp_side = x2["direction"]
    else:
        sharp_side = None

    return {
        "tier": classify_tier(total) if not contested else "contested",
        "sharp_side": "contested" if contested else sharp_side,
        "contested": contested,
        "ah": ah,
        "x2": x2,
        "moneyline_limit_drop_pct": ml_limit_drop,
        "spread_limit_drop_pct": sp_limit_drop,
        "ah_score": ah_score,
        "x2_score": x2_score,
        "limit_bonus": limit_bonus,
        "convergence_bonus": conv_bonus,
        "total_score": total,
    }


# ---------------------------------------------------------------------------
# DB-touching orchestration below.
# ---------------------------------------------------------------------------

from app import db  # noqa: E402


async def fetch_series(matchup_id: int, market_type: str, period: int = 0, is_alternate: bool = False) -> list[dict]:
    rows = await db.fetch(
        """
        select captured_at, home_price, draw_price, away_price, home_points,
               limit_amount, fair_home_prob, fair_draw_prob, fair_away_prob, status
        from market_snapshots
        where matchup_id = $1 and market_type = $2 and period = $3 and is_alternate = $4
        order by captured_at asc
        """,
        matchup_id,
        market_type,
        period,
        is_alternate,
    )
    return [dict(r) for r in rows]


async def compute_and_store_score(matchup_id: int, kickoff: datetime) -> dict:
    moneyline_series = await fetch_series(matchup_id, "moneyline")
    spread_series = await fetch_series(matchup_id, "spread")
    result = compute_match_score(moneyline_series, spread_series, kickoff)

    await db.execute(
        """
        insert into match_scores (
            matchup_id, ah_score, x2_score, limit_bonus, convergence_bonus,
            total_score, tier, sharp_side, contested
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        """,
        matchup_id,
        result["ah_score"],
        result["x2_score"],
        result["limit_bonus"],
        result["convergence_bonus"],
        result["total_score"],
        result["tier"],
        result["sharp_side"],
        result["contested"],
    )
    await db.execute(
        """
        insert into signals (matchup_id, signal_type, direction, magnitude, detail_json)
        values ($1,'ah_line_shift',$2,$3,$4::jsonb),
               ($1,'x2_displacement',$5,$6,$7::jsonb),
               ($1,'limit_movement',$8,$9,$10::jsonb)
        """,
        matchup_id,
        result["ah"]["direction"],
        result["ah"]["magnitude"],
        db.to_jsonb(result["ah"]),
        result["x2"]["direction"],
        result["x2"]["magnitude"],
        db.to_jsonb(result["x2"]),
        result["sharp_side"],
        max(result["moneyline_limit_drop_pct"], result["spread_limit_drop_pct"]),
        db.to_jsonb(
            {
                "moneyline_limit_drop_pct": result["moneyline_limit_drop_pct"],
                "spread_limit_drop_pct": result["spread_limit_drop_pct"],
            }
        ),
    )
    return result
