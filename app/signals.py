"""Market-movement readings used by the dashboard.

The tier / score engine (strong sharp, sharp, watch, no signal, with its
scoring and Telegram tier alerts) has been removed: it never showed any
predictive value. What remains is pure functions of a match's stored
snapshots, computed on demand:

  - ah_line_shift / x2_displacement - how far the AH line and the 1X2 fair
    probabilities have moved from the opening line (shown as cards)
  - favorite_strength              - who the opening line says is the favorite
  - velocity_shape / move_spans    - the shape of each move on a 1X2 line
  - steam_moves                    - which sides have had a steam move, ranked

The thresholds in CONFIG come from the original spec or from backtests noted
beside them; none has been shown to predict results.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

CONFIG = {
    "ah_shift_syndicate": 1.0,
    "ah_shift_sharp": 0.5,
    "ah_shift_threshold": 0.25,  # below this, not attributed as a signal at all
    "x2_strong_pp": 1.80,
    "x2_meaningful_pp": 0.80,
    "x2_noise_floor_pp": 0.30,
    # velocity_shape() only - kept separate from x2_noise_floor_pp on
    # purpose so tuning the real scored threshold never silently changes
    # this still-unproven, watch-only signal too.
    "velocity_floor_pp": 0.30,
    # move_span_min_pp: smallest swing on a 1X2 line that gets a move shape (and a
    # colour) on the chart; the engine's own "meaningful" 1X2 move size.
    "move_span_min_pp": 0.80,
    # steam_moves(): a steam swing is "late" when it finished within this many
    # hours of kickoff, "early" when it finished earlier. 3h is the same window
    # velocity_shape() uses to judge whether a move was fast enough to be steam.
    "late_steam_hours": 3.0,
    "velocity_window_hours": 3.0,
    "velocity_min_window_hours": 0.25,  # 15 min - below this, a window is too short to be meaningful given real poll spacing
    "velocity_steam_ratio": 0.70,
    "velocity_drift_ratio": 0.20,
    # favorite_strength() hard rule (RESEARCH_FINDINGS.md section 10): how
    # big the final 1X2 gap must be, in the underdog's favor, before a lead
    # change overrides the opening-line favorite. Backtested on 20 real
    # lead-change matches at a sweep of floors (0/1/2/5/10pp); 2.0 keeps
    # 18 of those 20 while still clearing real noise. Small sample -
    # trusted here per explicit user direction rather than left watch-only.
    "lead_change_min_gap_pp": 2.0,
    # favorite_strength() confirming-move confidence (RESEARCH_FINDINGS.md
    # section 12): thresholds for the biggest individual 1X2 zigzag swing
    # that agrees with the OPENING AH favorite. Backtested on every
    # individual swing pooled across 115 matches - "moderate" (>=1pp)
    # covers accuracy climbing from ~49% to ~58%, "strong" (>=4pp) covers
    # 73.3% (n=15) and 80.0% (n=5pp+, n=10). An OPPOSING swing of the same
    # size stays weak (17-39%), which is why this only ever boosts
    # confidence in the existing favorite - it never changes who it is.
    "confirming_move_meaningful_pp": 1.0,
    "confirming_move_strong_pp": 4.0,
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


def _zigzag_moves(values: list[float], min_reversal_frac: float = 0.001) -> list[tuple[float, str]]:
    """Breaks a chronological probability series (as raw 0-1 fractions)
    into its individual zigzag swings - every real reversal of at least
    min_reversal_frac (default 0.1pp), not just the net opening-to-final
    move. Returns (magnitude_pp, side) pairs, side being 'home' if that
    particular swing rose, 'away' if it fell. See favorite_strength()'s
    confirming-move confidence for why this matters: a swing's own
    magnitude, checked on its own against the real result, turned out to
    carry real signal even when the market later reversed that exact
    swing (RESEARCH_FINDINGS.md section 12).
    """
    if len(values) < 2:
        return []
    pivots = [values[0]]
    direction = 0
    extreme = values[0]
    for v in values[1:]:
        if direction == 0:
            if v > values[0]:
                direction, extreme = 1, v
            elif v < values[0]:
                direction, extreme = -1, v
            continue
        if direction == 1:
            if v >= extreme:
                extreme = v
            elif extreme - v >= min_reversal_frac:
                pivots.append(extreme)
                direction, extreme = -1, v
        else:
            if v <= extreme:
                extreme = v
            elif v - extreme >= min_reversal_frac:
                pivots.append(extreme)
                direction, extreme = 1, v
    pivots.append(extreme if direction != 0 else values[-1])

    moves = []
    for i in range(len(pivots) - 1):
        start, end = pivots[i], pivots[i + 1]
        moves.append((abs(end - start) * 100.0, "home" if end > start else "away"))
    return moves


def favorite_strength(spread_series: list[dict], moneyline_series: list[dict]) -> dict:
    """Identifies the favorite from the OPENING Asian Handicap line - before
    any money has landed - and estimates how strong that favorite actually
    is using the OPENING 1X2 fair probability for that same side, not the
    AH probability. The AH probability stays pinned near 50% regardless of
    how big the line is (it's the line's whole job to keep the covering
    probability close to a coin flip no matter the real quality gap), so it
    can't measure strength on its own - the 1X2 market can.

    Backtested against 115 real matches: the opening line's favorite won
    68.1% of non-draw matches, strengthening with the size of the line
    (50% at n=18 for +-0.5pt+, 80% at n=5 for +-1.0pt+). The 1X2 probability
    tracks the line size cleanly (pick'em ~38%, 0.25pt ~42%, 0.50pt ~48%,
    0.75-1.00pt ~60-63%, 1.50pt+ ~71%), and a stronger 1X2 reading makes the
    favorite more reliable too (50% at >=50%, 80% at >=60%, n=5). Samples
    past the 0.5pt / 50% mark are thin (single digits) - this is an early,
    directional read, not a precisely calibrated one. See
    RESEARCH_FINDINGS.md sections 6, 7 and 9 for the full backtest.

    HARD RULE - lead change override (RESEARCH_FINDINGS.md section 10):
    if the 1X2 market's own favorite has genuinely flipped by the most
    recent reading - the underdog's probability has overtaken the original
    favorite's by at least CONFIG["lead_change_min_gap_pp"] - that reversal
    overrides the opening-line favorite entirely. Backtested on 20 real
    lead-change matches: the original favorite's win rate drops from 48.4%
    (no lead change) to 35.0% (any lead change) to 22.2% once the final gap
    clears 2pp (n=9) - a small but consistent, strengthening pattern,
    trusted here per explicit user direction rather than left watch-only.

    CONFIDENCE BOOST - confirming move (RESEARCH_FINDINGS.md section 12):
    separately, the single biggest 1X2 zigzag swing that agrees with the
    OPENING AH favorite is itself informative, even when checked on its
    own regardless of whether that swing later got reversed. Backtested
    on every individual swing pooled across 115 matches: a confirming
    swing's accuracy climbs cleanly from 49.0% (>=0.5pp) to 58.3% (>=3pp)
    to 73.3% (>=4pp, n=15) to 80.0% (>=5pp, n=10) - while an OPPOSING
    swing of the same size stays weak throughout (17.2% to 38.5%),
    confirming this is a real asymmetry, not noise. This never changes
    WHO the favorite is (that's the lead-change rule above, which uses a
    stricter, persisted-to-the-end definition) - it only raises confidence
    in the favorite already identified.
    """
    opening_points, _ = _first_last(spread_series, "home_points")
    if opening_points is None:
        return {
            "favorite": None, "opening_favorite": None, "opening_line": None,
            "favorite_prob": None, "lead_change": False, "lead_change_gap_pp": None,
            "confirming_move_pp": None, "confidence": "none",
        }

    if opening_points < 0:
        opening_favorite = "home"
    elif opening_points > 0:
        opening_favorite = "away"
    else:
        opening_favorite = None

    opening_home_prob, current_home_prob = _first_last(moneyline_series, "fair_home_prob")
    opening_away_prob, current_away_prob = _first_last(moneyline_series, "fair_away_prob")

    favorite = opening_favorite
    favorite_prob = None
    if opening_favorite is not None:
        opening_fav_prob = opening_home_prob if opening_favorite == "home" else opening_away_prob
        favorite_prob = opening_fav_prob * 100.0 if opening_fav_prob is not None else None

    # The backtest behind this rule (section 10) is a PURELY 1X2-internal
    # before/after comparison - the 1X2 market's own opening favorite vs
    # its own current leader - independent of what the AH line says. Using
    # the AH-derived opening_favorite here instead would wrongly fire on a
    # single-snapshot match where the AH line and 1X2 market simply
    # disagree from the very start (zero real movement involved) - a
    # different, untested situation, not the one that was backtested.
    x2_opening_favorite = None
    if opening_home_prob is not None and opening_away_prob is not None:
        x2_opening_favorite = "home" if opening_home_prob > opening_away_prob else "away"

    lead_change = False
    lead_change_gap_pp = None
    if (
        x2_opening_favorite is not None
        and current_home_prob is not None
        and current_away_prob is not None
    ):
        final_leader = "home" if current_home_prob > current_away_prob else "away"
        gap_pp = abs(current_home_prob - current_away_prob) * 100.0
        if final_leader != x2_opening_favorite and gap_pp >= CONFIG["lead_change_min_gap_pp"]:
            favorite = final_leader
            favorite_prob = (current_home_prob if final_leader == "home" else current_away_prob) * 100.0
            lead_change = True
            lead_change_gap_pp = gap_pp

    # Confirming-move confidence boost - checked against the OPENING AH
    # favorite specifically (not the lead-change-adjusted one above), since
    # that's exactly what was backtested. Only ever raises confidence; it
    # cannot change which side is reported as the favorite.
    confirming_move_pp = None
    confidence = "none"
    if opening_favorite is not None:
        valid_ml = sorted(
            (s for s in moneyline_series if s.get("fair_home_prob") is not None and s.get("status") != "suspended"),
            key=lambda s: s["captured_at"],
        )
        home_prob_series = [s["fair_home_prob"] for s in valid_ml]
        confirming_magnitudes = [
            mag for mag, side in _zigzag_moves(home_prob_series) if side == opening_favorite
        ]
        if confirming_magnitudes:
            confirming_move_pp = max(confirming_magnitudes)
            if confirming_move_pp >= CONFIG["confirming_move_strong_pp"]:
                confidence = "strong"
            elif confirming_move_pp >= CONFIG["confirming_move_meaningful_pp"]:
                confidence = "moderate"

    return {
        "favorite": favorite,
        "opening_favorite": opening_favorite,
        "opening_line": opening_points,
        "favorite_prob": favorite_prob,
        "lead_change": lead_change,
        "lead_change_gap_pp": lead_change_gap_pp,
        "confirming_move_pp": confirming_move_pp,
        "confidence": confidence,
    }


def x2_displacement(moneyline_series: list[dict]) -> dict:
    """moneyline_series: chronological list of
    {captured_at, fair_home_prob, fair_draw_prob, fair_away_prob, status}.
    Displacement is in percentage points (pp), from the true opening line
    (the first stored snapshot, not an arbitrary baseline).

    Fixed flaw: an earlier version only ever compared home vs away, so
    "draw" could never come out as the direction - even though jackpot
    rounds always include matches that end in draws. The three fair
    probabilities are de-vigged, so they always sum to 1 at both ends:
    home_pp + draw_pp + away_pp ≈ 0, money can't land on one side without
    leaving the others. So whichever of the three has the single most
    POSITIVE pp change is the one actually being backed - that also
    naturally lets draw win when it's the side seeing real money.

    KNOWN LIMITATION, investigated and deliberately left alone: this only
    ever compares the true opening snapshot to the current one, so a move
    that happened and then reversed can look like nothing happened at all.
    `peak_side`/`peak_pp`/`swung_back` below surface that history so it's
    not lost - but they do NOT feed magnitude/direction/the score. Tested
    the alternative (scoring off the peak instead of the final number)
    against 32 real MJP matches with real results: the final number's
    direction matched the actual outcome 13/32 times vs only 7/32 for the
    peak, and on the 9 matches where they disagreed the final number was
    right 7 times to the peak's 1. Small sample, but it points the
    opposite way from the intuition that "the peak is the truer signal" -
    a reversal usually means the market's settled view (wrong-footed
    money got out, or conviction faded) is more informative than the
    high-water mark it passed through. So the peak is shown, not scored.
    """
    result = {
        "home_pp": 0.0, "draw_pp": 0.0, "away_pp": 0.0, "magnitude": 0.0, "direction": None,
        "peak_side": None, "peak_pp": 0.0, "swung_back": False,
    }
    for outcome in ("home", "draw", "away"):
        opening, current = _first_last(moneyline_series, f"fair_{outcome}_prob")
        if opening is not None and current is not None:
            result[f"{outcome}_pp"] = (current - opening) * 100.0

    candidates = {"home": result["home_pp"], "draw": result["draw_pp"], "away": result["away_pp"]}
    leading_side = max(candidates, key=lambda k: candidates[k])
    magnitude = abs(candidates[leading_side])
    result["magnitude"] = magnitude
    if magnitude >= CONFIG["x2_noise_floor_pp"]:
        result["direction"] = leading_side

    peak_candidates = {}
    for outcome in ("home", "draw", "away"):
        field = f"fair_{outcome}_prob"
        valid = [s for s in moneyline_series if s.get(field) is not None and s.get("status") != "suspended"]
        if len(valid) < 2:
            peak_candidates[outcome] = 0.0
            continue
        opening_val = valid[0][field]
        best = max(valid, key=lambda s: (s[field] - opening_val) * 100.0)
        peak_candidates[outcome] = (best[field] - opening_val) * 100.0

    peak_side = max(peak_candidates, key=lambda k: peak_candidates[k])
    peak_pp = peak_candidates[peak_side]
    if abs(peak_pp) >= CONFIG["x2_noise_floor_pp"]:
        result["peak_side"] = peak_side
        result["peak_pp"] = peak_pp
        # the side that peaked has since come most of the way back
        result["swung_back"] = abs(candidates[peak_side]) < CONFIG["x2_noise_floor_pp"]
    return result


def velocity_shape(moneyline_series: list[dict], side: str | None = None) -> dict:
    """Classifies HOW a 1X2 move happened over time, not just how big it
    got: a fast move concentrated in the recent window ("steam"), an old
    move that already happened and has since gone quiet ("drift"), a move
    still actively accumulating ("building"), one now heading back the
    other way ("reversal"), or one that swung away from the opening line
    and came most of the way back by the time we're checking ("swung_back").

    WATCH-ONLY - not wired into ah_score, x2_score, or the tier badge. The
    dashboard no longer shows it as a card: move_spans() below replays this
    classification per move and the shapes colour the 1X2 probability chart.
    Backtested against 2 real MJP rounds (32 matches, one confirmed non-
    jackpot test fixture excluded) on the AH line first: that line only
    ever moved in single atomic 0.25pt jumps, giving this classification
    nothing to actually distinguish. Re-run on the 1X2 series instead
    (real, continuous movement, not quantized steps), across 3h/6h/12h
    windows: "steam" and "building" calls were right about 70-100% of the
    time, "drift" calls only about 20-50% - a real, consistent pattern
    across all three windows tried. But the samples behind each label
    were tiny (as few as 2-5 decisive matches per label per window) -
    promising, not proven. Surfaced on the dashboard so it can keep being
    checked against real outcomes as more rounds come in, exactly like
    every other number in this file that started as a plain guess.

    Three known gaps, found and fixed after the first version shipped:
    - The look-back window used to be fixed (e.g. always 3h), which meant
      any match tracked for under 2x that window got no read at all,
      however big a move happened. It now shrinks to fit whatever history
      actually exists (down to `velocity_min_window_hours`), so an early
      real move still gets classified, just against a shorter recent
      slice - and if there genuinely isn't a usable window yet, it still
      honestly says "insufficient_history" rather than guessing.
    - A big swing that fully reverts by the time of the latest snapshot
      used to be invisible: opening-vs-current would show ~0 change, so
      it was called "quiet" even though something real happened along the
      way. Now the single largest deviation from the opening value,
      anywhere in the whole series, is tracked too - if that peak cleared
      the floor even though the net change didn't, it's labelled
      "swung_back" instead of being silently absorbed into "quiet".
    - It used to only ever compare home vs away, the same flaw
      x2_displacement() had: draw could never be the side a move was
      measured on, and the result never said which side (home/draw/away)
      the move was even about - a "steam" label alone didn't say steam on
      what. Both are fixed the same way: all three pp changes are
      computed, the one with the most POSITIVE change is the side the
      move is about (see x2_displacement()'s docstring for why "most
      positive" is the right test), and that side is now returned as
      `result["side"]`.

    `side` forces the side to classify instead of picking the most positive
    one; move_spans() uses it to read the shape of a swing on a specific line.
    """
    c = CONFIG
    configured_window = c["velocity_window_hours"]
    min_window = c["velocity_min_window_hours"]
    floor = c["velocity_floor_pp"]
    result = {
        "label": None,
        "side": None,
        "total_change_pp": 0.0,
        "recent_change_pp": None,
        "peak_change_pp": None,
        "window_hours": configured_window,
    }

    valid = [
        s for s in moneyline_series
        if s.get("fair_home_prob") is not None and s.get("fair_draw_prob") is not None
        and s.get("fair_away_prob") is not None and s.get("status") != "suspended"
    ]
    if len(valid) < 2:
        return result

    opening, current = valid[0], valid[-1]
    candidates = {
        outcome: (current[f"fair_{outcome}_prob"] - opening[f"fair_{outcome}_prob"]) * 100.0
        for outcome in ("home", "draw", "away")
    }
    if side is None:
        side = max(candidates, key=lambda k: candidates[k])
    field = f"fair_{side}_prob"
    total_change = candidates[side]
    result["side"] = side
    result["total_change_pp"] = total_change

    opening_val = opening[field]
    peak_point = max(valid, key=lambda s: abs((s[field] - opening_val) * 100.0))
    peak_change = (peak_point[field] - opening_val) * 100.0
    result["peak_change_pp"] = peak_change

    if abs(total_change) < floor:
        result["label"] = "swung_back" if abs(peak_change) >= floor else "quiet"
        return result

    last_dt, first_dt = current["captured_at"], opening["captured_at"]
    total_history_hours = (last_dt - first_dt).total_seconds() / 3600.0
    effective_window = min(configured_window, total_history_hours / 2.0)
    if effective_window < min_window:
        result["label"] = "insufficient_history"
        return result
    result["window_hours"] = effective_window

    cutoff = last_dt - timedelta(hours=effective_window)
    older = [s for s in valid if s["captured_at"] <= cutoff]
    if not older:
        result["label"] = "insufficient_history"
        return result

    baseline = older[-1]
    recent_change = (current[field] - baseline[field]) * 100.0
    result["recent_change_pp"] = recent_change

    if (recent_change > 0) != (total_change > 0) and abs(recent_change) >= floor:
        result["label"] = "reversal"
        return result

    ratio = abs(recent_change) / abs(total_change) if total_change else 0.0
    if ratio >= c["velocity_steam_ratio"]:
        result["label"] = "steam"
    elif ratio <= c["velocity_drift_ratio"]:
        result["label"] = "drift"
    else:
        result["label"] = "building"
    return result


MOVE_SHAPES = ("steam", "building", "drift", "reversal", "swung_back")


def _zigzag_pivot_indices(values: list[float], min_reversal_frac: float = 0.001) -> list[int]:
    """Indices of the zigzag pivots of a chronological series - the same
    swings as _zigzag_moves(), but returning where they happen."""
    n = len(values)
    if n < 2:
        return []
    pivots = [0]
    direction = 0
    ext = 0
    for i in range(1, n):
        v = values[i]
        if direction == 0:
            if v > values[0]:
                direction, ext = 1, i
            elif v < values[0]:
                direction, ext = -1, i
            continue
        if direction == 1:
            if v >= values[ext]:
                ext = i
            elif values[ext] - v >= min_reversal_frac:
                pivots.append(ext)
                direction, ext = -1, i
        else:
            if v <= values[ext]:
                ext = i
            elif v - values[ext] >= min_reversal_frac:
                pivots.append(ext)
                direction, ext = 1, i
    pivots.append(ext if direction != 0 else n - 1)
    return pivots


def move_spans(moneyline_series: list[dict], min_move_pp: float | None = None) -> list[dict]:
    """The individual moves on each 1X2 line, with the shape of each, for
    colouring the 1X2 fair-probability chart.

    A move is one zigzag swing of at least `min_move_pp` (default
    CONFIG["move_span_min_pp"]) on a side's fair probability, from where it
    started to where it stopped. Its shape is the label velocity_shape()
    gives for that side at the moment the swing stopped - so the chart uses
    the engine's own definitions (steam, building, drift, reversal, swung
    back), applied to each move as it ended instead of only to the match's
    latest state. A swing where the side already sits clearly below its
    opening level is skipped (that is money leaving, not a move onto the
    side), as is any swing the classifier calls quiet or has no history for;
    those stretches keep the line's normal colour.

    Returns [{"from", "to", "side", "label", "change_pp"}] sorted by start.
    A pure function of the series, so it works for old matches too.
    """
    min_move = CONFIG["move_span_min_pp"] if min_move_pp is None else min_move_pp
    valid = [
        s for s in moneyline_series
        if s.get("fair_home_prob") is not None and s.get("fair_draw_prob") is not None
        and s.get("fair_away_prob") is not None and s.get("status") != "suspended"
    ]
    if len(valid) < 3:
        return []
    spans: list[dict] = []
    for side in ("home", "draw", "away"):
        values = [s[f"fair_{side}_prob"] for s in valid]
        pivots = _zigzag_pivot_indices(values)
        for a, b in zip(pivots, pivots[1:]):
            change = (values[b] - values[a]) * 100.0
            if abs(change) < min_move:
                continue
            r = velocity_shape(valid[: b + 1], side=side)
            if r["label"] not in MOVE_SHAPES or r["total_change_pp"] < -CONFIG["velocity_floor_pp"]:
                continue
            # the swing's pivot can sit at the end of a flat stretch's start;
            # the move really began where the line last stood still before going
            start = a
            while start + 1 < b and (values[start + 1] - values[start]) * (1 if change > 0 else -1) <= 1e-9:
                start += 1
            spans.append({
                "from": valid[start]["captured_at"],
                "to": valid[b]["captured_at"],
                "side": side,
                "label": r["label"],
                "change_pp": change,
            })
    spans.sort(key=lambda g: (g["from"], g["side"]))
    return spans


def ah_view(spread_series: list[dict]) -> dict:
    """The AH line card: ah_line_shift() plus, when the line itself has not
    moved, the move in the price at that line (the flat-line fallback - a
    harder or easier line mechanically moves the covering probability, so the
    probability read only substitutes in when the line is unchanged)."""
    ah = ah_line_shift(spread_series)
    ah["prob_fallback_used"] = ah["magnitude"] < CONFIG["ah_shift_threshold"]
    ah["prob_fallback"] = x2_displacement(spread_series)
    return ah


def steam_moves(moneyline_series: list[dict], kickoff: datetime | None = None) -> list[dict]:
    """Every side that has had a steam move at any moment, ranked by the size
    of its biggest steam move (largest first).

    Built from move_spans(): a steam move is one swing of at least
    CONFIG["move_span_min_pp"] on a side's fair probability that
    velocity_shape() reads as steam when it stopped. Per side this returns the
    biggest such swing (magnitude_pp, from, to) and how many steam moves the
    side has had. Sides without a steam move are not listed.

    With the match's kickoff, each swing is also labelled by when it finished:
    "late" if within CONFIG["late_steam_hours"] of kickoff, else "early". Each
    side then carries the timing of its biggest swing (timing), the biggest
    early and late swings separately (early_pp, late_pp; None if there was
    none), and every steam swing (swings, biggest first) - so the ranked
    magnitude can be traced to the swing it came from. Without a kickoff the
    timing fields are None.
    """
    late_hours = CONFIG["late_steam_hours"]

    def timing_of(end) -> tuple[str | None, float | None]:
        if kickoff is None:
            return None, None
        try:
            hours = (kickoff - end).total_seconds() / 3600.0
        except TypeError:
            return None, None
        return ("late" if hours <= late_hours else "early"), round(hours, 2)

    swings: dict[str, list[dict]] = {}
    for span in move_spans(moneyline_series):
        if span["label"] != "steam":
            continue
        timing, hours = timing_of(span["to"])
        swings.setdefault(span["side"], []).append({
            "magnitude_pp": abs(span["change_pp"]), "change_pp": span["change_pp"],
            "from": span["from"], "to": span["to"],
            "timing": timing, "hours_before_kickoff": hours,
        })
    out = []
    for side, items in swings.items():
        items.sort(key=lambda x: x["magnitude_pp"], reverse=True)
        best = items[0]
        biggest = lambda timing: next((x["magnitude_pp"] for x in items if x["timing"] == timing), None)
        out.append({
            "side": side, "magnitude_pp": best["magnitude_pp"], "count": len(items),
            "from": best["from"], "to": best["to"],
            "timing": best["timing"], "hours_before_kickoff": best["hours_before_kickoff"],
            "early_pp": biggest("early"), "late_pp": biggest("late"),
            "swings": items,
        })
    return sorted(out, key=lambda e: e["magnitude_pp"], reverse=True)


def x2_transitions(moneyline_series: list[dict], max_evaluations: int = 400) -> list[dict]:
    """History of which side the 1X2 displacement read favoured, replayed over
    the series: one entry each time that reading changed (for the History
    dropdown on the 1X2 displacement card). Long series are sampled."""
    valid = [
        s for s in moneyline_series
        if s.get("fair_home_prob") is not None and s.get("fair_draw_prob") is not None
        and s.get("fair_away_prob") is not None and s.get("status") != "suspended"
    ]
    n = len(valid)
    if n < 2:
        return []
    step = max(1, n // max_evaluations)
    indices = list(range(2, n + 1, step))
    if indices and indices[-1] != n:
        indices.append(n)
    out: list[dict] = []
    last = object()
    for k in indices:
        label = x2_displacement(valid[:k])["direction"]
        if label != last:
            out.append({"at": valid[k - 1]["captured_at"], "label": label, "side": None, "change_pp": None})
            last = label
    return out
